"""tmux session backend: container lifecycle, output logging, and tmux helpers.

These three concerns are kept together because they reference each other tightly:
killing a session stops its container, the watcher reaps both, and tmux_start
sets up the per-session log file. The HTTP layer talks to this module only
through the functions it exports.
"""

import hashlib
import os
import re
import shlex
import subprocess
import threading
import time

from .settings import (
    HOST_ID,
    LOG_DIR,
    LOG_MAX_AGE_SECONDS,
)

# ── Container lifecycle tracking ───────────────────────────────────────────────
# Maps tmux session name → toolbox container name so we can stop the container
# when the session ends (via kill API, natural exit, or external tmux kill).
_session_containers: dict[str, str] = {}
_containers_lock = threading.Lock()


def _container_for_session(session: str) -> str | None:
    """Look up the container for a session (in-memory, then tmux env fallback)."""
    with _containers_lock:
        if session in _session_containers:
            return _session_containers[session]
    # Fallback: tmux environment variable survives a Flask restart
    r = subprocess.run(
        ["tmux", "show-environment", "-t", session, "TOOLBOX_CONTAINER"],
        capture_output=True,
        text=True,
    )
    if r.returncode == 0 and "=" in r.stdout:
        return r.stdout.strip().split("=", 1)[1]
    return None


def _stop_container(container: str) -> None:
    subprocess.run(
        ["podman", "stop", "--time", "5", container],
        capture_output=True,
        timeout=30,
    )


def _containers_in_use(exclude_session: str | None = None) -> set[str]:
    """Set of containers that still have at least one live tmux session."""
    in_use: set[str] = set()
    for s in tmux_list_sessions():
        if s["name"] == exclude_session:
            continue
        c = _container_for_session(s["name"])
        if c:
            in_use.add(c)
    return in_use


def _stop_container_if_unused(
    container: str, exclude_session: str | None = None
) -> None:
    """Stop the container only when no other live session is using it."""
    if not container:
        return
    if container in _containers_in_use(exclude_session):
        return
    _stop_container(container)


# ── Output logging ─────────────────────────────────────────────────────────────
# Strip ANSI/VT escape sequences (CSI, OSC, and lone two-byte escapes).
_ANSI_RE = re.compile(
    r"\x1b\[[0-9;?]*[ -/]*[@-~]"  # CSI ... final byte
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC ... BEL or ST
    r"|\x1b[@-Z\\-_]"  # other two-byte escapes
)
# Strip stray control chars but keep tab (\x09) and newline (\x0a).
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _log_path(session: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", session)
    return os.path.join(LOG_DIR, f"{safe}.log")


def _clean_text(raw: bytes) -> str:
    """Decode raw pane bytes and drop escape/control sequences for display."""
    s = _CTRL_RE.sub("", _ANSI_RE.sub("", raw.decode("utf-8", "replace")))
    # tmux panes emit CRLF; normalise so a lone \r means a true line overwrite.
    return s.replace("\r\n", "\n")


def _split_lines(text: str) -> list[str]:
    """Split already-complete text into display lines, applying \\r overwrite."""
    out = []
    for ln in text.split("\n"):
        if "\r" in ln:
            ln = ln.split("\r")[-1]  # carriage return overwrites the line
        out.append(ln)
    return out


def _prune_logs() -> None:
    cutoff = time.time() - LOG_MAX_AGE_SECONDS
    try:
        for fn in os.listdir(LOG_DIR):
            if not fn.endswith(".log"):
                continue
            p = os.path.join(LOG_DIR, fn)
            try:
                if os.path.getmtime(p) < cutoff:
                    os.remove(p)
            except OSError:
                pass
    except OSError:
        pass


def _session_watcher() -> None:
    """Periodically stop containers whose tmux sessions have exited externally."""
    ticks = 0
    while True:
        time.sleep(15)
        try:
            live = {s["name"] for s in tmux_list_sessions()}
            dead_containers: set[str] = set()
            with _containers_lock:
                for sess in list(_session_containers):
                    if sess not in live:
                        dead_containers.add(_session_containers.pop(sess))
            # Stop a dead session's container only if no surviving session uses it.
            in_use = _containers_in_use()
            for container in dead_containers:
                if container and container not in in_use:
                    _stop_container(container)
            ticks += 1
            if ticks % 40 == 0:  # ~every 10 min
                _prune_logs()
        except Exception:
            pass


# ── tmux helpers ───────────────────────────────────────────────────────────────


def _session_name(container: str, cmd: str) -> str:
    """Derive a stable, tmux-safe session name from container + command."""
    binary = cmd.strip().split()[0].split("/")[-1] if cmd.strip() else "cmd"
    # Include a short hash of the full command so two commands with the same
    # binary (e.g. llama-server vs llama-server --tools all) get distinct sessions
    cmd_hash = hashlib.sha1(cmd.strip().encode()).hexdigest()[:6]
    raw = f"{container}-{binary}-{cmd_hash}"
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", raw)[:64]
    return safe


def tmux_list_sessions() -> list[dict]:
    """Return all live tmux sessions as dicts {name, created, attached, windows}."""
    try:
        r = subprocess.run(
            [
                "tmux",
                "list-sessions",
                "-F",
                "#{session_name}|#{session_created}|#{session_attached}|#{session_windows}",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        sessions = []
        for line in r.stdout.strip().splitlines():
            if not line:
                continue
            parts = line.split("|", 3)
            if len(parts) == 4:
                sessions.append(
                    {
                        "name": parts[0],
                        "created": int(parts[1]) if parts[1].isdigit() else 0,
                        "attached": int(parts[2]) if parts[2].isdigit() else 0,
                        "windows": int(parts[3]) if parts[3].isdigit() else 0,
                    }
                )
        return sessions
    except Exception:
        return []


def tmux_session_exists(name: str) -> bool:
    r = subprocess.run(
        ["tmux", "has-session", "-t", name],
        capture_output=True,
    )
    return r.returncode == 0


def tmux_kill_session(name: str) -> bool:
    container = _container_for_session(name)
    r = subprocess.run(["tmux", "kill-session", "-t", name], capture_output=True)
    with _containers_lock:
        _session_containers.pop(name, None)
    if container:
        # Stop the container asynchronously (so the API response isn't delayed),
        # and only if no other live session is still using it.
        threading.Thread(
            target=_stop_container_if_unused, args=(container, name), daemon=True
        ).start()
    return r.returncode == 0


def tmux_capture(name: str, lines: int = 2000) -> str:
    """Capture scrollback + visible pane content from a tmux session."""
    r = subprocess.run(
        ["tmux", "capture-pane", "-t", name, "-p", "-S", f"-{lines}"],
        capture_output=True,
        text=True,
        timeout=5,
    )
    return r.stdout if r.returncode == 0 else ""


def tmux_start(container: str, cmd: str, session: str) -> bool:
    """Launch a new tmux session running the command (in a toolbox, or on the host)."""
    if container == HOST_ID:
        # Host maintenance command — run via a login shell so the user's env
        # (HF_HOME, PATH, …) is set up. The bundled HF scripts use the project
        # venv, so no `hf` on PATH is required. No toolbox, no container.
        inner = f"bash -lc {shlex.quote(cmd)}"
    else:
        inner = f"toolbox run --container {shlex.quote(container)} bash -c {shlex.quote(cmd)}"
    # No eager `podman stop` here: several sessions can share one container, so a
    # short command finishing must not tear down a long-running server alongside
    # it. Container teardown is reference-counted (see _stop_container_if_unused).
    r = subprocess.run(
        ["tmux", "new-session", "-d", "-s", session, "-x", "220", "-y", "50", inner],
        capture_output=True,
    )
    if r.returncode == 0:
        if container != HOST_ID:
            # Persist container name in tmux env (survives Flask restart) + dict.
            subprocess.run(
                [
                    "tmux",
                    "set-environment",
                    "-t",
                    session,
                    "TOOLBOX_CONTAINER",
                    container,
                ],
                capture_output=True,
            )
            with _containers_lock:
                _session_containers[session] = container
        # Tee this session's raw output to a log file for robust streaming.
        log = _log_path(session)
        try:
            open(log, "w").close()  # start fresh; ensures the file exists immediately
        except OSError:
            pass
        subprocess.run(
            ["tmux", "pipe-pane", "-t", session, f"cat >> {shlex.quote(log)}"],
            capture_output=True,
        )
    return r.returncode == 0


def _start_host(cmd: str) -> str | None:
    """Start a host (bash -lc) tmux session for cmd; return its name (or None)."""
    session = _session_name(HOST_ID, cmd)
    if not tmux_session_exists(session) and not tmux_start(HOST_ID, cmd, session):
        return None
    return session
