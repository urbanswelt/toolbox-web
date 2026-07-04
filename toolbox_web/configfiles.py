"""commands.yaml loading/caching, the editable-file allowlist, text validators,
atomic writes, and the raw config-editor HTTP routes.

This is the shared config layer: the command builder (commands.py), preset
builder (presets.py), and model scan (models.py) all read the cache and reuse
the validators / atomic-write helper defined here.
"""

import configparser
import os
import re
import threading

import yaml
from flask import Blueprint, jsonify, request

from .settings import (
    CONFIG_PATH,
    CONFIG_TOKEN,
    DEFAULT_TOOLBOX_REPOS,
    EXTRA_EDITABLE,
    PRESETS_DIR,
)

bp = Blueprint("configfiles", __name__)


def _editable_files() -> list[dict]:
    """Allowlist of editable files, rebuilt each call so new .ini files appear."""
    files = [{"id": "commands.yaml", "path": CONFIG_PATH, "type": "yaml"}]
    try:
        for fn in sorted(os.listdir(PRESETS_DIR)):
            if fn.endswith(".ini"):
                files.append(
                    {"id": fn, "path": os.path.join(PRESETS_DIR, fn), "type": "ini"}
                )
    except OSError:
        pass
    files.extend(EXTRA_EDITABLE)
    return files


def _resolve_editable(file_id: str | None) -> dict | None:
    """Map a requested file id to its allowlisted entry (commands.yaml default).

    Also allows a *new* .ini file to be created in the presets dir, as long as the
    name is a plain basename (no path separators / traversal) ending in .ini.
    """
    target = file_id or "commands.yaml"
    existing = next((f for f in _editable_files() if f["id"] == target), None)
    if existing:
        return existing
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*\.ini", target):
        return {
            "id": target,
            "path": os.path.join(PRESETS_DIR, target),
            "type": "ini",
            "new": True,
        }
    return None


_MATCH_TYPES = {"exact", "prefix", "suffix", "contains", "regex", "default"}

# Fallback used if the config file is missing or unparseable.
_FALLBACK_COMMAND = {
    "cmd": "bash",
    "label": "Interactive shell",
    "description": "Opens a plain interactive bash shell inside the toolbox.",
}

_config_lock = threading.Lock()
_config_cache: dict = {"mtime": None, "rules": [], "host": [], "toolbox_repos": []}


def _build_matcher(match: dict):
    """Turn a {type, value} match spec into a predicate on the container name."""
    spec = match or {}
    mtype = spec.get("type", "default")
    value = spec.get("value", "")
    if mtype == "exact":
        return lambda n: n == value
    if mtype == "prefix":
        return lambda n: n.startswith(value)
    if mtype == "suffix":
        return lambda n: n.endswith(value)
    if mtype == "contains":
        return lambda n: value in n
    if mtype == "regex":
        rx = re.compile(value)
        return lambda n: rx.search(n) is not None
    # "default" (or anything unknown) → catch-all
    return lambda n: True


def _normalize_command(c) -> dict:
    """Accept either a bare string or a {cmd,label,description} mapping."""
    if isinstance(c, str):
        return {"cmd": c, "label": "", "description": ""}
    return {
        "cmd": str(c.get("cmd", "")).strip(),
        "label": str(c.get("label", "") or "").strip(),
        "description": " ".join(str(c.get("description", "") or "").split()),
    }


def load_config() -> list[dict]:
    """
    Return the parsed rule list, reloading from disk only when the file's
    mtime changes. On a parse error the last good config is kept and reused.
    """
    try:
        mtime = os.path.getmtime(CONFIG_PATH)
    except OSError:
        return _config_cache["rules"]

    with _config_lock:
        if mtime == _config_cache["mtime"]:
            return _config_cache["rules"]
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            rules = []
            for r in data.get("rules", []):
                commands = [_normalize_command(c) for c in r.get("commands", [])]
                commands = [c for c in commands if c["cmd"]]
                rules.append(
                    {"match": _build_matcher(r.get("match")), "commands": commands}
                )
            host = [_normalize_command(c) for c in data.get("host_commands", [])]
            host = [c for c in host if c["cmd"]]
            tb = []
            for r in data.get("toolbox_repos", []):
                if not isinstance(r, dict):
                    continue
                name, path = (
                    str(r.get("name", "")).strip(),
                    str(r.get("path", "")).strip(),
                )
                if name and path:
                    tb.append(
                        {
                            "name": name,
                            "path": os.path.expanduser(path),
                            "update": str(r.get("update", "") or "").strip(),
                        }
                    )
            _config_cache["rules"] = rules
            _config_cache["host"] = host
            _config_cache["toolbox_repos"] = tb
            _config_cache["mtime"] = mtime
        except Exception as e:
            # Keep serving the previous config; log so journalctl shows the error.
            print(f"[toolbox-web] failed to load {CONFIG_PATH}: {e}", flush=True)
        return _config_cache["rules"]


def get_commands_for(name: str) -> list[dict]:
    """Return the list of command dicts for a container, first matching rule wins."""
    for rule in load_config():
        if rule["match"](name) and rule["commands"]:
            return rule["commands"]
    return [_FALLBACK_COMMAND]


def get_host_commands() -> list[dict]:
    """Commands that run directly on the host (Maintenance section)."""
    load_config()
    return _config_cache.get("host", [])


def get_toolbox_repos() -> list[dict]:
    """Toolbox source repos for the update manager (config, else built-in default)."""
    load_config()
    return _config_cache.get("toolbox_repos") or DEFAULT_TOOLBOX_REPOS


def validate_config_text(text: str) -> tuple[bool, str]:
    """
    Parse + structurally validate raw YAML config text.
    Returns (ok, message). On failure, message describes the first problem.
    """
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" (line {mark.line + 1}, column {mark.column + 1})" if mark else ""
        return False, f"YAML syntax error{where}: {getattr(e, 'problem', e)}"

    if data is None:
        return False, "Config is empty — expected a top-level 'rules:' list."
    if not isinstance(data, dict) or "rules" not in data:
        return False, "Top-level must be a mapping with a 'rules:' key."
    if not isinstance(data["rules"], list) or not data["rules"]:
        return False, "'rules' must be a non-empty list."

    for i, rule in enumerate(data["rules"], 1):
        if not isinstance(rule, dict):
            return False, f"Rule #{i} must be a mapping."
        match = rule.get("match", {"type": "default"})
        if not isinstance(match, dict):
            return False, f"Rule #{i}: 'match' must be a mapping."
        mtype = match.get("type", "default")
        if mtype not in _MATCH_TYPES:
            return False, (
                f"Rule #{i}: match type '{mtype}' is invalid "
                f"(use {', '.join(sorted(_MATCH_TYPES))})."
            )
        if mtype not in ("default",) and not str(match.get("value", "")).strip():
            return False, f"Rule #{i}: match type '{mtype}' needs a 'value'."
        if mtype == "regex":
            try:
                re.compile(str(match.get("value", "")))
            except re.error as e:
                return False, f"Rule #{i}: invalid regex — {e}."
        cmds = rule.get("commands", [])
        if not isinstance(cmds, list) or not cmds:
            return False, f"Rule #{i}: 'commands' must be a non-empty list."
        for j, c in enumerate(cmds, 1):
            if isinstance(c, str):
                if not c.strip():
                    return False, f"Rule #{i}, command #{j}: command is empty."
            elif isinstance(c, dict):
                if not str(c.get("cmd", "")).strip():
                    return False, f"Rule #{i}, command #{j}: missing 'cmd'."
            else:
                return False, (
                    f"Rule #{i}, command #{j}: must be a string or a "
                    f"mapping with a 'cmd' key."
                )
    return True, "Config is valid."


def validate_ini_text(text: str) -> tuple[bool, str]:
    """Validate llama.cpp preset INI text (lenient — matches what llama reads)."""
    cp = configparser.ConfigParser(
        strict=False, allow_no_value=True, interpolation=None
    )
    try:
        cp.read_string(text)
    except configparser.Error as e:
        return False, f"INI syntax error: {str(e).splitlines()[0]}"
    if not cp.sections():
        return (
            False,
            "No sections found — expected at least one [*] or [preset/...] block.",
        )
    presets = [s for s in cp.sections() if s.startswith("preset/")]
    return True, f"Valid INI — {len(cp.sections())} sections, {len(presets)} preset(s)."


def validate_sh_text(text: str) -> tuple[bool, str]:
    """Syntax-check a shell script with `bash -n` (parses, never executes)."""
    import subprocess
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".sh", encoding="utf-8") as tf:
        tf.write(text)
        tf.flush()
        r = subprocess.run(["bash", "-n", tf.name], capture_output=True, text=True)
    if r.returncode == 0:
        return True, "Valid shell syntax."
    err = (r.stderr.strip().splitlines() or ["see bash -n"])[-1]
    return False, f"Shell syntax error: {err}"


def validate_models_text(text: str) -> tuple[bool, str]:
    """Validate the curated model list (config/models.yaml)."""
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" (line {mark.line + 1}, column {mark.column + 1})" if mark else ""
        return False, f"YAML syntax error{where}: {getattr(e, 'problem', e)}"
    if data is None:
        return False, "Empty — expected a top-level 'models:' list."
    if not isinstance(data, dict) or "models" not in data:
        return False, "Top-level must be a mapping with a 'models:' key."
    if not isinstance(data["models"], list):
        return False, "'models' must be a list."
    for i, m in enumerate(data["models"], 1):
        if not isinstance(m, dict):
            return False, f"Entry #{i} must be a mapping."
        if not str(m.get("name", "")).strip():
            return False, f"Entry #{i}: missing 'name'."
        if not str(m.get("repo", "")).strip():
            return False, f"Entry #{i}: missing 'repo'."
    return True, f"Valid — {len(data['models'])} model(s)."


def _validate_for(entry: dict, text: str) -> tuple[bool, str]:
    t = entry["type"]
    if t == "ini":
        return validate_ini_text(text)
    if t == "sh":
        return validate_sh_text(text)
    if t == "models":
        return validate_models_text(text)
    return validate_config_text(text)


def write_text_atomic(path: str, text: str) -> None:
    """Atomically replace a file, keeping a .bak and preserving its mode."""
    tmp = f"{path}.tmp.{os.getpid()}"
    mode = None
    try:
        if os.path.exists(path):
            mode = os.stat(path).st_mode  # preserve perms (e.g. +x scripts)
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
            try:
                import shutil

                shutil.copy2(path, f"{path}.bak")
            except OSError:
                pass
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass


# ── Routes ─────────────────────────────────────────────────────────────────────


@bp.route("/api/config/files")
def api_config_files():
    """List the files the editor may open (commands.yaml + llama preset .ini's)."""
    return jsonify(
        {
            "files": [
                {"id": f["id"], "type": f["type"], "exists": os.path.exists(f["path"])}
                for f in _editable_files()
            ],
            "token_required": bool(CONFIG_TOKEN),
        }
    )


@bp.route("/api/config", methods=["GET"])
def api_config_get():
    """Return the raw text of an editable file (commands.yaml by default)."""
    entry = _resolve_editable(request.args.get("file"))
    if not entry:
        return jsonify({"error": "Unknown file"}), 404
    try:
        with open(entry["path"], encoding="utf-8") as f:
            text = f.read()
        exists = True
    except OSError:
        text, exists = "", False
    return jsonify(
        {
            "text": text,
            "exists": exists,
            "path": entry["path"],
            "id": entry["id"],
            "type": entry["type"],
            "token_required": bool(CONFIG_TOKEN),
        }
    )


@bp.route("/api/config/validate", methods=["POST"])
def api_config_validate():
    """Validate submitted text (YAML or INI) for the given file without writing."""
    entry = _resolve_editable(request.args.get("file"))
    if not entry:
        return jsonify({"ok": False, "message": "Unknown file"}), 404
    text = (request.get_json(silent=True) or {}).get("text", "")
    ok, msg = _validate_for(entry, text)
    return jsonify({"ok": ok, "message": msg})


@bp.route("/api/config", methods=["POST"])
def api_config_save():
    """Validate then atomically write an editable file (keeps a .bak)."""
    if CONFIG_TOKEN and request.headers.get("X-Toolbox-Token", "") != CONFIG_TOKEN:
        return jsonify({"ok": False, "message": "Invalid or missing token."}), 403

    entry = _resolve_editable(request.args.get("file"))
    if not entry:
        return jsonify({"ok": False, "message": "Unknown file"}), 404

    text = (request.get_json(silent=True) or {}).get("text", "")
    ok, msg = _validate_for(entry, text)
    if not ok:
        return jsonify({"ok": False, "message": msg}), 400
    try:
        write_text_atomic(entry["path"], text)
    except OSError as e:
        return jsonify({"ok": False, "message": f"Write failed: {e}"}), 500

    if entry["type"] == "yaml":
        # Force a reload on the next request so command changes take effect now.
        with _config_lock:
            _config_cache["mtime"] = None
        return jsonify({"ok": True, "message": "Saved. Changes are live."})
    if entry["type"] == "ini":
        return jsonify(
            {
                "ok": True,
                "message": "Saved. Takes effect next time you start llama-server.",
            }
        )
    return jsonify({"ok": True, "message": "Saved. Takes effect next run."})
