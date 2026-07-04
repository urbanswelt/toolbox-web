"""Structured command builder (form-based, comment-preserving).

A friendlier, non-technical alternative to hand-editing commands.yaml. The
browser sends a single structured operation (add / update / delete a command)
and the server applies it to the YAML document using ruamel.yaml round-trip
loading, so every human-written comment and the formatting in commands.yaml is
preserved. The result is then run through the same validate + atomic-write +
cache-bust path the raw editor uses, so the form can never save a broken file.
"""

import io
import re

import yaml
from flask import Blueprint, jsonify, request

from .configfiles import (
    _MATCH_TYPES,
    _config_cache,
    _config_lock,
    _normalize_command,
    validate_config_text,
    write_text_atomic,
)
from .settings import CONFIG_PATH, CONFIG_TOKEN
from .toolboxes import list_toolboxes

bp = Blueprint("commands", __name__)


def _ruamel():
    """Lazily build a configured ruamel YAML(); return None if it isn't installed."""
    try:
        from ruamel.yaml import YAML
    except Exception:
        return None
    y = YAML()
    y.preserve_quotes = True
    y.width = 4096  # never let ruamel hard-wrap our long command lines
    y.indent(
        mapping=2, sequence=4, offset=2
    )  # keep list dashes indented under their key
    return y


def _match_label(match: dict) -> str:
    """Human-friendly description of a match spec, for the 'apply to' picker."""
    t = (match or {}).get("type", "default")
    v = str((match or {}).get("value", "") or "")
    if t == "default":
        return "all other toolboxes (default)"
    human = {
        "exact": "name is",
        "prefix": "name starts with",
        "suffix": "name ends with",
        "contains": "name contains",
        "regex": "name matches",
    }.get(t, t)
    return f"{human} “{v}”"


def commands_to_json() -> dict:
    """Parse commands.yaml into a plain structure the builder form can render."""
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        data = {}
    rules_out = []
    for i, r in enumerate(data.get("rules", []) or []):
        match = dict((r.get("match") or {"type": "default"}))
        cmds = [_normalize_command(c) for c in (r.get("commands") or [])]
        rules_out.append(
            {
                "index": i,
                "match": {
                    "type": match.get("type", "default"),
                    "value": str(match.get("value", "") or ""),
                },
                "label": _match_label(match),
                "commands": cmds,
            }
        )
    return {
        "rules": rules_out,
        "toolboxes": sorted({b["name"] for b in list_toolboxes() if b.get("name")}),
        "match_types": ["exact", "prefix", "suffix", "contains", "regex", "default"],
        "ruamel": _ruamel() is not None,
        "token_required": bool(CONFIG_TOKEN),
    }


def _new_cmd_map(cmd: str, label: str, description: str):
    """Build a ruamel CommentedMap for one command, using a block scalar if multi-line."""
    from ruamel.yaml.comments import CommentedMap
    from ruamel.yaml.scalarstring import PreservedScalarString

    m = CommentedMap()
    cmd = cmd.rstrip("\n")
    m["cmd"] = PreservedScalarString(cmd) if "\n" in cmd else cmd
    if label:
        m["label"] = label
    if description:
        m["description"] = description
    return m


def apply_command_op(op: dict) -> tuple[bool, str, str | None]:
    """Apply one builder operation to commands.yaml.

    Returns (ok, message, new_text). new_text is the fully-rendered YAML (comments
    preserved) ready to write; None on any failure.
    """
    y = _ruamel()
    if y is None:
        return (
            False,
            "The form builder needs the 'ruamel.yaml' package "
            "(pip install --user ruamel.yaml).",
            None,
        )
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            doc = y.load(f)
    except OSError as e:
        return False, f"Could not read config: {e}", None
    if (
        not isinstance(doc, dict)
        or "rules" not in doc
        or not isinstance(doc["rules"], list)
    ):
        return False, "commands.yaml has no 'rules:' list to edit.", None
    rules = doc["rules"]

    action = op.get("op")
    label = (op.get("label") or "").strip()
    desc = " ".join((op.get("description") or "").split())
    cmd = (op.get("cmd") or "").strip()

    try:
        if action in ("add_command", "update_command") and not cmd:
            return False, "Command is empty.", None

        if action == "add_command":
            newc = _new_cmd_map(cmd, label, desc)
            tgt = op.get("target") or {}
            if tgt.get("kind") == "existing":
                idx = int(tgt.get("index"))
                if not (0 <= idx < len(rules)):
                    return False, "That rule no longer exists — reload and retry.", None
                rules[idx].setdefault("commands", [])
                rules[idx]["commands"].append(newc)
            else:
                from ruamel.yaml.comments import CommentedMap, CommentedSeq

                mtype = tgt.get("type") or "default"
                mval = (tgt.get("value") or "").strip()
                if mtype not in _MATCH_TYPES:
                    return False, f"Invalid match type '{mtype}'.", None
                if mtype != "default" and not mval:
                    return False, "This match type needs a value.", None
                if mtype == "regex":
                    try:
                        re.compile(mval)
                    except re.error as e:
                        return False, f"Invalid regex — {e}.", None
                m = CommentedMap()
                m["type"] = mtype
                if mtype != "default":
                    m["value"] = mval
                rule = CommentedMap()
                rule["match"] = m
                seq = CommentedSeq()
                seq.append(newc)
                rule["commands"] = seq
                # Keep first-match semantics: insert just before any default catch-all.
                pos = len(rules)
                for k, r in enumerate(rules):
                    if ((r.get("match") or {}).get("type", "default")) == "default":
                        pos = k
                        break
                rules.insert(pos, rule)

        elif action == "update_command":
            ri, ci = int(op["rule_index"]), int(op["cmd_index"])
            cmds = rules[ri]["commands"]
            cmds[ci] = _new_cmd_map(cmd, label, desc)

        elif action == "delete_command":
            ri, ci = int(op["rule_index"]), int(op["cmd_index"])
            del rules[ri]["commands"][ci]
            if not rules[ri]["commands"]:
                del rules[ri]  # drop a rule once its last command is gone

        else:
            return False, f"Unknown operation '{action}'.", None
    except KeyError, IndexError, ValueError, TypeError:
        return False, "That command no longer exists — reload and retry.", None

    buf = io.StringIO()
    y.dump(doc, buf)
    text = buf.getvalue()
    ok, msg = validate_config_text(text)
    if not ok:
        return False, f"Change rejected (would be invalid): {msg}", None
    return True, "ok", text


@bp.route("/api/commands", methods=["GET"])
def api_commands_get():
    """Structured view of commands.yaml for the form builder."""
    return jsonify(commands_to_json())


@bp.route("/api/commands", methods=["POST"])
def api_commands_post():
    """Apply one builder op (add/update/delete) and write commands.yaml."""
    if CONFIG_TOKEN and request.headers.get("X-Toolbox-Token", "") != CONFIG_TOKEN:
        return jsonify({"ok": False, "message": "Invalid or missing token."}), 403
    op = request.get_json(silent=True) or {}
    ok, msg, text = apply_command_op(op)
    if not ok:
        return jsonify({"ok": False, "message": msg}), 400
    try:
        write_text_atomic(CONFIG_PATH, text)
    except OSError as e:
        return jsonify({"ok": False, "message": f"Write failed: {e}"}), 500
    with _config_lock:
        _config_cache["mtime"] = None  # force hot-reload on next request
    return jsonify({"ok": True, "message": "Saved. Changes are live."})
