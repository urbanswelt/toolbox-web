"""Model management: Hugging Face cache scanning, the curated models.yaml list,
"unused model" detection, and the related HTTP routes.
"""

import io
import json
import os
import re
import shlex
import subprocess
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

import yaml
from flask import Blueprint, jsonify, request

from .configfiles import (
    _config_cache,
    _editable_files,
    load_config,
    write_text_atomic,
)
from .presets import _parse_ini_presets
from .sessions import _start_host
from .settings import (
    CONFIG_TOKEN,
    MODELS_DIR,
    MODELS_LIST_PATH,
    SCRIPTS_DIR,
    SYNC_MODELS_SCRIPT,
    VENV_PYTHON,
)

bp = Blueprint("models", __name__)

# ── Model management (Hugging Face cache) ──────────────────────────────────────
_hf_cache = {"dir": None}


def _hf_cache_dir() -> str:
    """Resolve the HF hub cache dir the same way the scripts do (via login shell)."""
    if _hf_cache["dir"]:
        return _hf_cache["dir"]
    d = ""
    try:
        r = subprocess.run(
            [
                "bash",
                "-lc",
                'printf %s "${HF_HUB_CACHE:-${HF_HOME:-$HOME/.cache/huggingface}/hub}"',
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        d = r.stdout.strip()
    except Exception:
        pass
    _hf_cache["dir"] = d or os.path.expanduser("~/.cache/huggingface/hub")
    return _hf_cache["dir"]


def _list_cached_models() -> list[dict]:
    """Enumerate cached HF models (repo id, on-disk size, ~/models symlinks)."""
    cache = _hf_cache_dir()
    # Map the model-store symlinks to their resolved targets, to flag what's linked.
    links: dict[str, str] = {}
    mdir = MODELS_DIR
    try:
        for name in os.listdir(mdir):
            p = os.path.join(mdir, name)
            if os.path.islink(p):
                links[name] = os.path.realpath(p)
    except OSError:
        pass

    models = []
    try:
        entries = sorted(os.listdir(cache))
    except OSError:
        entries = []
    for d in entries:
        if not d.startswith("models--"):
            continue
        repo = d[len("models--") :].replace("--", "/")
        repo_path = os.path.join(cache, d)
        # Real bytes live in blobs/ (snapshots/ are just symlinks into blobs/).
        size = 0
        for root, _, files in os.walk(os.path.join(repo_path, "blobs")):
            for fn in files:
                try:
                    size += os.lstat(os.path.join(root, fn)).st_size
                except OSError:
                    pass
        linked = sorted(
            n
            for n, t in links.items()
            if t == repo_path or t.startswith(repo_path + os.sep)
        )
        models.append({"repo": repo, "size_kb": size // 1024, "linked": linked})
    return models


# ── Managed models (the curated config/models.yaml list) ───────────────────────
_sync_models_lock = threading.Lock()
_VALID_REPO = re.compile(r"^[A-Za-z0-9][\w.\-]*(?:/[A-Za-z0-9][\w.\-]*)?$")
_VALID_NAME = re.compile(r"^[A-Za-z0-9][\w.\-]*$")


def _parse_managed_models() -> dict:
    """Read config/models.yaml into {repo: {name, repo, pattern}}."""
    managed: dict[str, dict] = {}
    try:
        with open(MODELS_LIST_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except OSError, yaml.YAMLError:
        return managed
    for e in data.get("models") or []:
        if not isinstance(e, dict):
            continue
        repo = str(e.get("repo", "")).strip()
        if not repo:
            continue
        name = str(e.get("name", "")).strip() or repo.split("/")[-1]
        managed[repo] = {
            "name": name,
            "repo": repo,
            "pattern": str(e.get("pattern", "") or "*"),
        }
    return managed


def _append_model(name: str, repo: str, pattern: str) -> None:
    """Append a model entry to config/models.yaml (comment-preserving round-trip).
    No-op if the repo is already listed. Caller holds _sync_models_lock."""
    from ruamel.yaml import YAML
    from ruamel.yaml.comments import CommentedMap

    yml = YAML()
    yml.indent(mapping=2, sequence=2, offset=0)
    yml.width = 4096
    try:
        with open(MODELS_LIST_PATH, encoding="utf-8") as f:
            doc = yml.load(f)
    except FileNotFoundError:
        doc = None
    if not isinstance(doc, dict):
        doc = CommentedMap()
    models = doc.get("models")
    if models is None:
        doc["models"] = models = []
    if any(isinstance(m, dict) and str(m.get("repo")) == repo for m in models):
        return
    entry = CommentedMap([("name", name), ("repo", repo), ("pattern", pattern)])
    entry.fa.set_flow_style()  # one-line entry, matching the file
    models.append(entry)
    buf = io.StringIO()
    yml.dump(doc, buf)
    write_text_atomic(MODELS_LIST_PATH, buf.getvalue())


def _hf_token() -> str:
    """Resolve the HF token the same way the scripts do: env var, then stored file."""
    tok = os.environ.get("HF_TOKEN", "").strip()
    if tok:
        return tok
    hf_home = os.environ.get("HF_HOME", os.path.expanduser("~/.cache/huggingface"))
    try:
        with open(os.path.join(hf_home, "token"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _local_ref(repo: str) -> str:
    """The commit hash that 'main' points to in the local cache (refs/main)."""
    refs = os.path.join(
        _hf_cache_dir(), "models--" + repo.replace("/", "--"), "refs", "main"
    )
    try:
        with open(refs, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _remote_sha(repo: str, token: str) -> str:
    """Latest commit SHA for a repo from the HF API ('' on any error)."""
    req = urllib.request.Request(f"https://huggingface.co/api/models/{repo}")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return (json.loads(r.read().decode("utf-8")).get("sha") or "").strip()
    except Exception:
        return ""


def _check_one(repo: str, token: str) -> dict:
    local, remote = _local_ref(repo), _remote_sha(repo, token)
    if not local or not remote:
        status = "unknown"
    else:
        status = "uptodate" if local == remote else "update"
    return {"repo": repo, "status": status, "local": local[:12], "remote": remote[:12]}


# ── "Unused model" detection ───────────────────────────────────────────────────
# A model is "wired up" if some command (commands.yaml) or some preset (.ini)
# references it — vLLM repos by id (`vllm serve Org/Name`), llama models by path
# (`model = /…/x.gguf` or `-m /…/x.gguf`). Anything downloaded but referenced by
# neither is *likely unused* and flagged so it can be wired up (or reviewed).

_SPLIT_RE = re.compile(r"-(\d{5})-of-(\d{5})\.gguf$")


def _split_first_name(name: str) -> str:
    """Canonical first shard of a split GGUF (presets only name shard 1)."""
    m = _SPLIT_RE.search(name)
    return name[: m.start()] + f"-00001-of-{m.group(2)}.gguf" if m else name


def _first_gguf_in(dirpath: str) -> str:
    """Pick a representative .gguf in a dir (shard 1 / non-split), or '' if none."""
    try:
        ggufs = sorted(n for n in os.listdir(dirpath) if n.endswith(".gguf"))
    except OSError:
        return ""
    for n in ggufs:
        if "-00001-of-" in n or not _SPLIT_RE.search(n):
            return os.path.join(dirpath, n)
    return os.path.join(dirpath, ggufs[0]) if ggufs else ""


def _reference_blob() -> str:
    """All command strings + preset model paths — the text that 'wires up' a model."""
    load_config()
    parts = []
    for r in _config_cache.get("rules", []):
        parts += [c.get("cmd", "") for c in r.get("commands", [])]
    parts += [c.get("cmd", "") for c in _config_cache.get("host", [])]
    for entry in _editable_files():
        if entry["type"] != "ini":
            continue
        parsed = _parse_ini_presets(entry["path"])
        if parsed:
            parts += [p.get("model", "") for p in parsed["presets"] if p.get("model")]
    return "\n".join(parts)


def _repo_referenced(repo: str, linked: list[str], ref: str) -> bool:
    """True if the repo id (as a whole token) or any of its ~/models links appears."""
    if re.search(re.escape(repo) + r"(?![\w./-])", ref):
        return True
    return any(link and link in ref for link in linked)


def find_model_usage() -> dict:
    """Annotate cached repos with `used`, and find unused real .gguf files on disk."""
    ref = _reference_blob()

    repos = _list_cached_models()
    for m in repos:
        m["used"] = _repo_referenced(m["repo"], m.get("linked", []), ref)
        # For unused ones, classify so the UI offers the right quick action:
        # a GGUF repo → "+ preset" (with a concrete .gguf path); otherwise → "+ command".
        m["kind"], m["gguf_path"] = "hf", ""
        if not m["used"]:
            for link in m.get("linked", []):
                g = _first_gguf_in(os.path.join(MODELS_DIR, link))
                if g:
                    m["kind"], m["gguf_path"] = "gguf", g
                    break
            if m["kind"] == "hf" and m["repo"].upper().endswith("GGUF"):
                m["kind"] = "gguf"

    # Real (non-symlink) .gguf files under the models dir. Symlinks are skipped —
    # they resolve into an HF cache repo, which the repo scan above already covers.
    groups: dict[str, dict] = {}
    try:
        for root, _dirs, files in os.walk(MODELS_DIR):
            for fn in files:
                if not fn.endswith(".gguf"):
                    continue
                full = os.path.join(root, fn)
                if os.path.islink(full):
                    continue
                first = _split_first_name(fn)
                used = (fn in ref) or (first in ref) or (full in ref)
                key = os.path.join(root, first)  # group split shards as one model
                g = groups.setdefault(
                    key,
                    {
                        "path": os.path.join(root, first),
                        "name": first,
                        "size_kb": 0,
                        "used": False,
                        "shards": 0,
                    },
                )
                g["used"] = g["used"] or used
                g["shards"] += 1
                try:
                    g["size_kb"] += os.stat(full).st_size // 1024
                except OSError:
                    pass
            if len(groups) > 500:
                break
    except OSError:
        pass

    unused_repos = [m for m in repos if not m["used"]]
    unused_gguf = sorted(
        (g for g in groups.values() if not g["used"]), key=lambda g: -g["size_kb"]
    )
    return {
        "models": repos,
        "unused_gguf": unused_gguf,
        "unused_repo_count": len(unused_repos),
        "unused_repo_kb": sum(m["size_kb"] for m in unused_repos),
        "unused_gguf_count": len(unused_gguf),
        "unused_gguf_kb": sum(g["size_kb"] for g in unused_gguf),
    }


@bp.route("/api/models")
def api_models():
    usage = find_model_usage()
    models = usage["models"]
    managed = _parse_managed_models()
    for m in models:
        entry = managed.get(m["repo"])
        m["managed"] = bool(entry)
        m["link_name"] = entry["name"] if entry else ""
        m["pattern"] = entry["pattern"] if entry else ""
    return jsonify(
        {
            "models": models,
            "total_kb": sum(m["size_kb"] for m in models),
            "cache_dir": _hf_cache_dir(),
            "token_required": bool(CONFIG_TOKEN),
            "managed_count": len(managed),
            "unused_gguf": usage["unused_gguf"],
            "unused_repo_count": usage["unused_repo_count"],
            "unused_repo_kb": usage["unused_repo_kb"],
            "unused_gguf_count": usage["unused_gguf_count"],
            "unused_gguf_kb": usage["unused_gguf_kb"],
        }
    )


@bp.route("/api/drop-model", methods=["POST"])
def api_drop_model():
    """Delete a cached model via scripts/drop_model.py, streamed as a host session."""
    if CONFIG_TOKEN and request.headers.get("X-Toolbox-Token", "") != CONFIG_TOKEN:
        return jsonify({"error": "Invalid or missing token."}), 403
    repo = (request.get_json(silent=True) or {}).get("repo", "").strip()
    if repo not in {m["repo"] for m in _list_cached_models()}:
        return jsonify({"error": "Unknown or non-cached model."}), 400

    cmd = (
        f"{shlex.quote(VENV_PYTHON)} {shlex.quote(os.path.join(SCRIPTS_DIR, 'drop_model.py'))} "
        f"{shlex.quote(repo)}"
    )
    session = _start_host(cmd)
    if not session:
        return jsonify({"error": "Failed to start drop session."}), 500
    return jsonify({"session": session})


@bp.route("/api/check-updates", methods=["POST"])
def api_check_updates():
    """Compare every cached repo's local refs/main with the HF API (concurrently)."""
    repos = [m["repo"] for m in _list_cached_models()]
    token = _hf_token()
    results: dict[str, dict] = {}
    if repos:
        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = {ex.submit(_check_one, r, token): r for r in repos}
            for fut in as_completed(futs):
                try:
                    res = fut.result()
                except Exception:
                    res = {
                        "repo": futs[fut],
                        "status": "unknown",
                        "local": "",
                        "remote": "",
                    }
                results[res["repo"]] = res
    return jsonify({"results": results, "authenticated": bool(token)})


@bp.route("/api/download-model", methods=["POST"])
def api_download_model():
    """Download a new model via hf-link and remember it in the curated list."""
    if CONFIG_TOKEN and request.headers.get("X-Toolbox-Token", "") != CONFIG_TOKEN:
        return jsonify({"error": "Invalid or missing token."}), 403
    data = request.get_json(silent=True) or {}
    repo = (data.get("repo") or "").strip()
    name = (data.get("name") or "").strip() or repo.split("/")[-1]
    pattern = (data.get("pattern") or "").strip() or "*"
    if not _VALID_REPO.match(repo):
        return jsonify({"error": "Invalid repo id — expected 'org/name'."}), 400
    if not _VALID_NAME.match(name):
        return jsonify({"error": "Invalid local name."}), 400
    if "\n" in pattern or '"' in pattern or "'" in pattern:
        return jsonify({"error": "Invalid file pattern."}), 400

    # Persist to config/models.yaml unless the repo is already listed.
    if repo not in _parse_managed_models():
        try:
            with _sync_models_lock:
                _append_model(name, repo, pattern)
        except OSError as e:
            return jsonify({"error": f"Could not update models.yaml: {e}"}), 500

    cmd = (
        f"{shlex.quote(VENV_PYTHON)} {shlex.quote(os.path.join(SCRIPTS_DIR, 'hf_link.py'))} "
        f"{shlex.quote(name)} {shlex.quote(repo)} {shlex.quote(pattern)}"
    )
    session = _start_host(cmd)
    if not session:
        return jsonify({"error": "Failed to start download session."}), 500
    return jsonify({"session": session})


@bp.route("/api/update-model", methods=["POST"])
def api_update_model():
    """Re-pull a cached model's latest revision via its hf-link entry."""
    if CONFIG_TOKEN and request.headers.get("X-Toolbox-Token", "") != CONFIG_TOKEN:
        return jsonify({"error": "Invalid or missing token."}), 403
    repo = (request.get_json(silent=True) or {}).get("repo", "").strip()
    if repo not in {m["repo"] for m in _list_cached_models()}:
        return jsonify({"error": "Unknown or non-cached model."}), 400
    entry = _parse_managed_models().get(repo)
    name = entry["name"] if entry else repo.split("/")[-1]
    pattern = entry["pattern"] if entry else "*"
    cmd = (
        f"{shlex.quote(VENV_PYTHON)} {shlex.quote(os.path.join(SCRIPTS_DIR, 'hf_link.py'))} "
        f"{shlex.quote(name)} {shlex.quote(repo)} {shlex.quote(pattern)}"
    )
    session = _start_host(cmd)
    if not session:
        return jsonify({"error": "Failed to start update session."}), 500
    return jsonify({"session": session})


@bp.route("/api/sync-models", methods=["POST"])
def api_sync_models():
    """Run the whole curated list (download/update all, then prune)."""
    if CONFIG_TOKEN and request.headers.get("X-Toolbox-Token", "") != CONFIG_TOKEN:
        return jsonify({"error": "Invalid or missing token."}), 403
    session = _start_host(
        f"{shlex.quote(VENV_PYTHON)} {shlex.quote(SYNC_MODELS_SCRIPT)}"
    )
    if not session:
        return jsonify({"error": "Failed to start sync session."}), 500
    return jsonify({"session": session})
