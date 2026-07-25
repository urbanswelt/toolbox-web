"""App self-update check: is this checkout behind its GitHub remote?

A background thread periodically `git fetch`es and compares HEAD to the tracked
upstream branch, caching a small snapshot the UI polls (`/api/app-update`) to
show an "update available" banner. Nothing here mutates the repo — the actual
pull is SELF_UPDATE_CMD, which the banner button launches as a host session.
"""

import subprocess
import threading
import time

from flask import Blueprint, jsonify

from .settings import PROJECT_ROOT, SELF_UPDATE_CMD, SELF_UPDATE_INTERVAL

bp = Blueprint("updates", __name__)

_lock = threading.Lock()
_state: dict = {
    "available": False,   # True when behind > 0
    "behind": 0,          # commits on upstream not in HEAD
    "ahead": 0,           # local commits not yet pushed
    "branch": None,
    "incoming": [],       # [{sha, subject}] preview of what a pull would bring
    "checked_at": 0,      # epoch seconds of the last check
    "error": None,        # last fetch/parse error, if any (banner still hidden)
    "update_command": SELF_UPDATE_CMD,
}
# Set by the manual-check endpoint to wake the watcher for an immediate re-fetch.
_wake = threading.Event()


def _git(*args: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", PROJECT_ROOT, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _check_once() -> dict:
    """Fetch and diff HEAD against upstream; return a fresh snapshot (never raises)."""
    try:
        head = _git("rev-parse", "--abbrev-ref", "HEAD")
        if head.returncode != 0:
            return {"error": "not a git repository"}
        branch = head.stdout.strip()

        # Network step. A failure (offline, auth) shouldn't blank the banner — we
        # note the error but still diff against whatever the last fetch left us.
        fetch = _git("fetch", "--quiet", timeout=60)
        fetch_err = None if fetch.returncode == 0 else (
            fetch.stderr.strip().splitlines()[-1] if fetch.stderr.strip() else "git fetch failed"
        )

        # Prefer the configured tracking branch; fall back to origin/<branch>.
        up = _git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
        upstream = up.stdout.strip() if up.returncode == 0 else ""
        if not upstream:
            for cand in (f"origin/{branch}", "origin/HEAD"):
                if _git("rev-parse", "--verify", "--quiet", cand).returncode == 0:
                    upstream = cand
                    break
        if not upstream:
            return {"branch": branch, "error": fetch_err or "no upstream configured"}

        # left = ahead (in HEAD only), right = behind (in upstream only).
        counts = _git("rev-list", "--left-right", "--count", f"HEAD...{upstream}")
        ahead = behind = 0
        parts = counts.stdout.split()
        if counts.returncode == 0 and len(parts) == 2:
            ahead, behind = int(parts[0]), int(parts[1])

        incoming: list[dict] = []
        if behind:
            log = _git("log", "--no-merges", "--pretty=%h\t%s", f"HEAD..{upstream}", "-n", "20")
            if log.returncode == 0:
                for line in log.stdout.splitlines():
                    sha, _, subject = line.partition("\t")
                    incoming.append({"sha": sha, "subject": subject})

        return {
            "branch": branch,
            "upstream": upstream,
            "behind": behind,
            "ahead": ahead,
            "incoming": incoming,
            "error": fetch_err,
        }
    except Exception as e:  # subprocess timeout, git missing, parse error…
        return {"error": str(e)}


def _apply(res: dict) -> None:
    with _lock:
        _state.update(
            {
                "available": bool(res.get("behind")),
                "behind": res.get("behind", 0),
                "ahead": res.get("ahead", 0),
                "branch": res.get("branch"),
                "incoming": res.get("incoming", []),
                "error": res.get("error"),
                "checked_at": time.time(),
            }
        )


def _update_watcher() -> None:
    while True:
        _apply(_check_once())
        # Sleep until the interval elapses or a manual check wakes us.
        _wake.wait(timeout=SELF_UPDATE_INTERVAL)
        _wake.clear()


@bp.route("/api/app-update")
def api_app_update():
    """Latest cached self-update snapshot (polled by the header banner)."""
    with _lock:
        return jsonify(dict(_state))


@bp.route("/api/app-update/check", methods=["POST"])
def api_app_update_check():
    """Force an immediate re-fetch and return the fresh snapshot."""
    _apply(_check_once())
    with _lock:
        return jsonify(dict(_state))
