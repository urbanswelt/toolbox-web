"""Structured model-preset builder (llama.cpp .ini, comment-preserving).

Same idea as the command builder, for the llama.cpp preset .ini files. The .ini
files carry lots of human comments (URLs, section dividers, per-preset notes) and
the stdlib `configparser` can't round-trip those, so instead of re-serialising the
whole file we splice it by section: each [section] block keeps its own leading
comments + header verbatim, so adding a preset or editing/deleting one never
disturbs the comments of any *other* section.
"""

import configparser
import os
import re

from flask import Blueprint, jsonify, request

from .configfiles import (
    _editable_files,
    _resolve_editable,
    validate_ini_text,
    write_text_atomic,
)
from .settings import CONFIG_TOKEN, MODELS_DIR

bp = Blueprint("presets", __name__)

# Common per-preset knobs the form exposes as labelled fields, in write order.
# Anything else a preset uses (spec-type, cache-type-k, …) is round-tripped through
# the form's free-text "advanced" box.
COMMON_PRESET_FIELDS = [
    "ctx-size",
    "parallel",
    "temp",
    "top-p",
    "top-k",
    "min-p",
    "repeat-penalty",
]

_INI_HEADER_RE = re.compile(r"^\s*\[(.+?)\]\s*$")


def _is_blank_or_comment(line: str) -> bool:
    t = line.strip()
    return t == "" or t.startswith("#") or t.startswith(";")


def _split_ini_blocks(text: str) -> list[dict]:
    """Split INI text into per-section blocks, attaching leading comments/blank lines
    to the section that follows them. Each block: {name, lead[], header, body[]}."""
    blocks: list[dict] = []
    lead: list[str] = []
    cur: dict | None = None
    for line in text.split("\n"):
        m = _INI_HEADER_RE.match(line)
        if m:
            if cur is not None:
                blocks.append(cur)
            cur = {"name": m.group(1).strip(), "lead": lead, "header": line, "body": []}
            lead = []
        elif cur is None:
            lead.append(line)  # before the first section header
        elif _is_blank_or_comment(line):
            lead.append(line)  # may belong to the *next* section
        else:
            if lead:  # a real key=value flushes buffered
                cur["body"].extend(lead)
                lead = []  # comments into the current body
            cur["body"].append(line)
    if cur is not None:
        if lead:
            cur["body"].extend(lead)  # trailing comments after last section
        blocks.append(cur)
    return blocks


def _render_ini_blocks(blocks: list[dict]) -> str:
    out: list[str] = []
    for b in blocks:
        out.extend(b["lead"])
        out.append(b["header"])
        out.extend(b["body"])
    return "\n".join(out).rstrip("\n") + "\n"


def _gen_preset_body(model: str, fields: dict, advanced: str) -> list[str]:
    """Build the body lines for one [preset/...] section from the form inputs."""
    lines = []
    model = (model or "").strip()
    if model:
        lines.append(f"model = {model}")
    fields = fields or {}
    for k in COMMON_PRESET_FIELDS:
        v = str(fields.get(k, "") or "").strip()
        if v != "":
            lines.append(f"{k} = {v}")
    for raw in (advanced or "").splitlines():  # extra "key = value" lines verbatim
        if raw.strip():
            lines.append(raw.rstrip())
    return lines


def _gguf_suggestions(known_models: list[str]) -> list[str]:
    """Model-path suggestions: any .gguf under the models dir, plus paths already in use."""
    found = set(known_models or [])
    try:
        for root, _dirs, files in os.walk(MODELS_DIR):
            for fn in files:
                if fn.endswith(".gguf"):
                    found.add(os.path.join(root, fn))
            if len(found) > 400:  # keep it bounded on huge model dirs
                break
    except OSError:
        pass
    return sorted(found)


def _parse_ini_presets(path: str) -> dict | None:
    """Parse one .ini into {globals, presets:[{name, model, fields}]} for the form."""
    cp = configparser.ConfigParser(
        strict=False, allow_no_value=True, interpolation=None
    )
    cp.optionxform = str  # preserve key case
    try:
        with open(path, encoding="utf-8") as f:
            cp.read_file(f)
    except OSError, configparser.Error:
        return None
    globals_, presets = {}, []
    for sec in cp.sections():
        items = {k: (v if v is not None else "") for k, v in cp.items(sec)}
        if sec == "*":
            globals_ = items
        elif sec.startswith("preset/"):
            model = items.pop("model", "")
            presets.append(
                {"name": sec[len("preset/") :], "model": model, "fields": items}
            )
    return {"globals": globals_, "presets": presets}


def _ini_globals_text(path: str) -> str:
    """Raw body of the [*] section (keys + any inline comments), for the defaults editor."""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return ""
    for b in _split_ini_blocks(text):
        if b["name"] == "*":
            return "\n".join(b["body"]).strip("\n")
    return ""


def presets_to_json() -> dict:
    """Structured view of every model .ini for the preset form."""
    files, known_models = [], []
    for entry in _editable_files():
        if entry["type"] != "ini":
            continue
        parsed = _parse_ini_presets(entry["path"]) or {"globals": {}, "presets": []}
        for p in parsed["presets"]:
            if p["model"]:
                known_models.append(p["model"])
        files.append(
            {
                "id": entry["id"],
                "path": entry["path"],
                "globals": parsed["globals"],
                "globals_text": _ini_globals_text(entry["path"]),
                "presets": parsed["presets"],
            }
        )
    return {
        "files": files,
        "common_fields": COMMON_PRESET_FIELDS,
        "model_suggestions": _gguf_suggestions(known_models),
        "token_required": bool(CONFIG_TOKEN),
    }


_NEW_INI_DEFAULTS = ["[*]", "n-gpu-layers = 999", "flash-attn = on", "jinja = true"]


def apply_preset_op(op: dict) -> tuple[bool, str, str | None, str | None]:
    """Apply one preset op (add/update/delete) to a model .ini.

    Returns (ok, message, path, new_text). path/new_text are None on failure.
    """
    entry = _resolve_editable(op.get("file"))
    if not entry or entry["type"] != "ini":
        return False, "Choose a valid .ini file.", None, None
    path = entry["path"]
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        text = ""  # new file — start empty

    action = op.get("op")
    name = (op.get("name") or "").strip()
    if action in ("add_preset", "update_preset", "delete_preset") and not name:
        return False, "Preset name is required.", None, None
    if name and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", name):
        return False, "Preset name: use letters, digits, and . _ - / only.", None, None

    blocks = _split_ini_blocks(text) if text.strip() else []
    section = f"preset/{name}"

    if action == "add_preset":
        if any(b["name"] == section for b in blocks):
            return (
                False,
                f"A preset named '{name}' already exists in this file.",
                None,
                None,
            )
        if not (op.get("model") or "").strip():
            return False, "Pick a model file for the preset.", None, None
        if not any(b["name"] == "*" for b in blocks):
            blocks.insert(
                0,
                {
                    "name": "*",
                    "lead": ["# Global defaults for all presets"],
                    "header": "[*]",
                    "body": _NEW_INI_DEFAULTS[1:],
                },
            )
        blocks.append(
            {
                "name": section,
                "lead": [""],
                "header": f"[{section}]",
                "body": _gen_preset_body(
                    op.get("model"), op.get("fields"), op.get("advanced")
                ),
            }
        )
    elif action == "update_preset":
        blk = next((b for b in blocks if b["name"] == section), None)
        if blk is None:
            return False, "That preset no longer exists — reload and retry.", None, None
        if not (op.get("model") or "").strip():
            return False, "Pick a model file for the preset.", None, None
        blk["body"] = _gen_preset_body(
            op.get("model"), op.get("fields"), op.get("advanced")
        )
    elif action == "delete_preset":
        new_blocks = [b for b in blocks if b["name"] != section]
        if len(new_blocks) == len(blocks):
            return False, "That preset no longer exists — reload and retry.", None, None
        blocks = new_blocks
    elif action == "update_globals":
        body = [ln.rstrip() for ln in (op.get("text") or "").split("\n")]
        while body and body[-1].strip() == "":  # trim trailing blank lines
            body.pop()
        blk = next((b for b in blocks if b["name"] == "*"), None)
        if blk is None:
            blocks.insert(
                0,
                {
                    "name": "*",
                    "lead": ["# Global defaults for all presets"],
                    "header": "[*]",
                    "body": body,
                },
            )
        else:
            blk["body"] = body
    else:
        return False, f"Unknown operation '{action}'.", None, None

    new_text = _render_ini_blocks(blocks)
    ok, msg = validate_ini_text(new_text)
    if not ok:
        return False, f"Change rejected (would be invalid): {msg}", None, None
    return True, "ok", path, new_text


@bp.route("/api/presets", methods=["GET"])
def api_presets_get():
    """Structured view of the model .ini files for the preset form."""
    return jsonify(presets_to_json())


@bp.route("/api/presets", methods=["POST"])
def api_presets_post():
    """Apply one preset op (add/update/delete) and write the model .ini."""
    if CONFIG_TOKEN and request.headers.get("X-Toolbox-Token", "") != CONFIG_TOKEN:
        return jsonify({"ok": False, "message": "Invalid or missing token."}), 403
    op = request.get_json(silent=True) or {}
    ok, msg, path, text = apply_preset_op(op)
    if not ok:
        return jsonify({"ok": False, "message": msg}), 400
    try:
        write_text_atomic(path, text)
    except OSError as e:
        return jsonify({"ok": False, "message": f"Write failed: {e}"}), 500
    return jsonify(
        {"ok": True, "message": "Saved. Takes effect next time you start llama-server."}
    )
