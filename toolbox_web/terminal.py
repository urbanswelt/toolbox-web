"""The terminal layer: launching/killing/streaming tmux sessions, the per-container
command list, and the on-disk session log reader.

The stream endpoint tails each session's log file (LOG_DIR/<session>.log) by byte
offset; the log id is exactly the session name, so viewing a log reuses
/api/stream/<id> (which serves a dead session's full log and ends with `done`).
"""

import json
import os
import re
import time

from flask import Blueprint, Response, jsonify, request, stream_with_context

from .configfiles import get_commands_for, get_host_commands
from .sessions import (
    _clean_text,
    _log_path,
    _prune_logs,
    _session_name,
    _split_lines,
    tmux_capture,
    tmux_kill_session,
    tmux_list_sessions,
    tmux_session_exists,
    tmux_start,
)
from .settings import CONFIG_TOKEN, HOST_ID, LOG_BACKLOG_BYTES, LOG_DIR

bp = Blueprint("terminal", __name__)


# ── Log reader ─────────────────────────────────────────────────────────────────


def _log_id_to_path(log_id: str) -> str:
    """Resolve a log id to its file, re-sanitising to prevent path traversal."""
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", log_id)
    return os.path.join(LOG_DIR, f"{safe}.log")


@bp.route("/api/logs")
def api_logs():
    """List session log files (newest first), flagging which are still live."""
    _prune_logs()
    live = {s["name"] for s in tmux_list_sessions()}
    out = []
    try:
        for fn in os.listdir(LOG_DIR):
            if not fn.endswith(".log"):
                continue
            p = os.path.join(LOG_DIR, fn)
            try:
                st = os.stat(p)
            except OSError:
                continue
            sid = fn[:-4]
            out.append(
                {
                    "id": sid,
                    "size": st.st_size,
                    "mtime": int(st.st_mtime),
                    "live": sid in live,
                }
            )
    except OSError:
        pass
    out.sort(key=lambda x: x["mtime"], reverse=True)
    return jsonify({"logs": out, "dir": LOG_DIR, "token_required": bool(CONFIG_TOKEN)})


@bp.route("/api/logs/raw/<log_id>")
def api_log_raw(log_id: str):
    """Download a log as cleaned (ANSI-stripped) text/plain."""
    path = _log_id_to_path(log_id)
    if not os.path.isfile(path):
        return jsonify({"error": "No such log."}), 404
    try:
        with open(path, "rb") as f:
            text = _clean_text(f.read())
    except OSError as e:
        return jsonify({"error": str(e)}), 500
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", log_id)
    return Response(
        text,
        mimetype="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{safe}.log"'},
    )


@bp.route("/api/logs/delete", methods=["POST"])
def api_log_delete():
    """Delete a log file (not allowed while its session is still live)."""
    if CONFIG_TOKEN and request.headers.get("X-Toolbox-Token", "") != CONFIG_TOKEN:
        return jsonify({"error": "Invalid or missing token."}), 403
    log_id = (request.get_json(silent=True) or {}).get("id", "").strip()
    path = _log_id_to_path(log_id)
    if not os.path.isfile(path):
        return jsonify({"error": "No such log."}), 404
    if tmux_session_exists(log_id):
        return jsonify({"error": "Session is still live — kill it first."}), 409
    try:
        os.remove(path)
    except OSError as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"ok": True})


@bp.route("/api/logs/delete-all", methods=["POST"])
def api_logs_delete_all():
    """Delete every log whose session isn't still live; live ones are kept."""
    if CONFIG_TOKEN and request.headers.get("X-Toolbox-Token", "") != CONFIG_TOKEN:
        return jsonify({"error": "Invalid or missing token."}), 403
    live = {s["name"] for s in tmux_list_sessions()}
    deleted, skipped, freed = 0, 0, 0
    try:
        names = os.listdir(LOG_DIR)
    except OSError:
        names = []
    for fn in names:
        if not fn.endswith(".log"):
            continue
        if fn[:-4] in live:
            skipped += 1
            continue
        p = os.path.join(LOG_DIR, fn)
        try:
            sz = os.path.getsize(p)
            os.remove(p)
            deleted += 1
            freed += sz
        except OSError:
            pass
    return jsonify({"ok": True, "deleted": deleted, "skipped": skipped, "freed": freed})


@bp.route("/api/commands/<container_name>")
def api_commands(container_name: str):
    cmds = (
        get_host_commands()
        if container_name == HOST_ID
        else get_commands_for(container_name)
    )
    sessions = {s["name"] for s in tmux_list_sessions()}
    result = []
    for c in cmds:
        sname = _session_name(container_name, c["cmd"])
        result.append(
            {
                "command": c["cmd"],
                "label": c["label"],
                "description": c["description"],
                "session": sname,
                "running": sname in sessions,
            }
        )
    return jsonify(result)


@bp.route("/api/sessions")
def api_sessions():
    return jsonify(tmux_list_sessions())


@bp.route("/api/run", methods=["POST"])
def api_run():
    data = request.get_json()
    container = data.get("container")
    command = data.get("command")
    if not container or not command:
        return jsonify({"error": "Missing container or command"}), 400

    session = _session_name(container, command)

    if tmux_session_exists(session):
        return jsonify({"session": session, "reattached": True})

    ok = tmux_start(container, command, session)
    if not ok:
        return jsonify({"error": "Failed to start tmux session"}), 500

    return jsonify({"session": session, "reattached": False})


@bp.route("/api/kill/<session>", methods=["POST"])
def api_kill(session: str):
    ok = tmux_kill_session(session)
    return jsonify({"ok": ok})


@bp.route("/api/history/<session>")
def api_history(session: str):
    """Return existing scrollback for a session (for reconnect)."""
    if not tmux_session_exists(session):
        return jsonify({"lines": [], "exists": False})
    raw = tmux_capture(session)
    lines = raw.splitlines()
    return jsonify({"lines": lines, "exists": True})


def _sse(payload: dict, event_id: int | None = None) -> str:
    prefix = f"id: {event_id}\n" if event_id is not None else ""
    return f"{prefix}data: {json.dumps(payload)}\n\n"


def _stream_from_log(session: str, start_offset: int | None):
    """
    Tail the session's log file by byte offset (append-only, no line cap).

    Completed lines carry an `id:` equal to the committed byte offset, so an
    EventSource reconnect (which replays Last-Event-ID) resumes exactly where it
    left off with no duplication. In-progress lines (e.g. progress bars updating
    via \\r) are sent with `partial: true` and NO id, so they never advance the
    resume point — the incomplete tail is simply re-read after a reconnect.
    """
    path = _log_path(session)
    yield ": connected\n\n"

    # Decide where to start reading.
    try:
        size = os.path.getsize(path)
    except OSError:
        size = 0
    if start_offset is not None:
        committed = max(0, min(start_offset, size))
    elif size > LOG_BACKLOG_BYTES:
        # Fresh view of a large log: backfill only the tail, aligned to a line.
        with open(path, "rb") as f:
            f.seek(size - LOG_BACKLOG_BYTES)
            f.readline()  # discard the partial first line
            committed = f.tell()
        yield _sse(
            {"line": "… earlier output truncated (full log on disk) …", "meta": True}
        )
    else:
        committed = 0

    last_partial = None
    idle = 0
    while True:
        alive = tmux_session_exists(session)
        try:
            size = os.path.getsize(path)
        except OSError:
            size = committed

        if size > committed:
            with open(path, "rb") as f:
                f.seek(committed)
                data = f.read()
            if alive:
                # While running, only commit up to the last newline; the bytes
                # after it are an in-progress line sent as a (non-committing) partial.
                nl = data.rfind(b"\n")
                if nl != -1:
                    committed += nl + 1
                    for ln in _split_lines(_clean_text(data[: nl + 1]))[:-1]:
                        yield _sse({"line": ln}, event_id=committed)
                tail = data[nl + 1 :] if nl != -1 else data
                partial = _clean_text(tail).split("\r")[-1] if tail else ""
                if partial and partial != last_partial:
                    yield _sse({"line": partial, "partial": True})
                    last_partial = partial
            else:
                # Session ended: everything remaining is final, including a last
                # line with no trailing newline.
                committed = size
                text = _clean_text(data)
                if text.endswith("\n"):
                    text = text[:-1]  # drop the single terminating newline
                for ln in _split_lines(text):
                    yield _sse({"line": ln}, event_id=committed)
            idle = 0
        else:
            idle += 1

        if not alive and committed >= size:
            yield _sse({"done": True, "reason": "session_ended"})
            return
        if idle % 50 == 0:
            yield ": keepalive\n\n"
        time.sleep(0.1)


def _stream_from_capture(session: str):
    """Fallback for sessions started before pipe-pane logging existed."""
    yield ": connected\n\n"
    prev_lines: list[str] = []
    idle = 0
    while True:
        if not tmux_session_exists(session):
            yield _sse({"done": True, "reason": "session_ended"})
            return
        current = tmux_capture(session).splitlines()
        if current != prev_lines:
            new = (
                current[len(prev_lines) :]
                if len(current) >= len(prev_lines)
                else current
            )
            for line in new:
                yield _sse({"line": line})
            prev_lines = current
            idle = 0
        else:
            idle += 1
        if idle % 50 == 0:
            yield ": keepalive\n\n"
        time.sleep(0.1)


@bp.route("/api/stream/<session>")
def api_stream(session: str):
    """Stream a session's output via SSE, tailing its log file when available."""
    # Resume point: explicit ?offset=, else the EventSource Last-Event-ID header.
    start_offset: int | None = None
    raw_off = request.args.get("offset") or request.headers.get("Last-Event-ID")
    if raw_off is not None:
        try:
            start_offset = int(raw_off)
        except ValueError:
            start_offset = None

    def generate():
        # Wait up to 3 s for the session (or its log) to appear.
        for _ in range(15):
            if tmux_session_exists(session) or os.path.exists(_log_path(session)):
                break
            time.sleep(0.2)
        else:
            yield _sse({"error": "Session not found", "done": True})
            return

        if os.path.exists(_log_path(session)):
            yield from _stream_from_log(session, start_offset)
        else:
            yield from _stream_from_capture(session)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
