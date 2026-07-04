"""sync-models — download/refresh every model in config/models.yaml, then prune.

Library-based (huggingface_hub) port of the former bash `sync-models`. Reads the
curated list from config/models.yaml, links each repo into the model store
(reusing hf_link.link), then deletes detached cache revisions (the library
equivalent of `hf cache prune`). No `hf` CLI on PATH is required. Run with the
project .venv interpreter (app.py and commands.yaml invoke it directly).
"""

import os
import sys

import yaml
from huggingface_hub import scan_cache_dir
from huggingface_hub.errors import CacheNotFound

import hf_link  # sibling module in scripts/


def models_list_path() -> str:
    """config/models.yaml, overridable via TOOLBOX_WEB_MODELS_LIST."""
    env = os.environ.get("TOOLBOX_WEB_MODELS_LIST")
    if env:
        return env
    here = os.path.dirname(os.path.abspath(__file__))  # scripts/
    return os.path.join(os.path.dirname(here), "config", "models.yaml")


def _prune_detached() -> None:
    """Delete cache revisions no ref points to — same intent as `hf cache prune`."""
    try:
        info = scan_cache_dir()
    except CacheNotFound:
        print("No cache found — nothing to prune.")
        return
    detached = [
        rev.commit_hash for repo in info.repos for rev in repo.revisions if not rev.refs
    ]
    if not detached:
        print("No detached revisions to prune.")
        return
    print(f"Pruning {len(detached)} detached revision(s)…")
    info.delete_revisions(*detached).execute()


def main() -> int:
    path = models_list_path()
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    entries = data.get("models", []) or []
    total = len(entries)
    failures = 0

    for i, e in enumerate(entries, 1):
        name = str((e or {}).get("name", "")).strip()
        repo = str((e or {}).get("repo", "")).strip()
        pattern = str((e or {}).get("pattern", "") or "").strip()
        if not name or not repo:
            print(f"[{i}/{total}] SKIP malformed entry: {e!r}", file=sys.stderr)
            failures += 1
            continue
        tag = f"  ({pattern})" if pattern else ""
        print(f"[{i}/{total}] {repo}  ->  ~/models/{name}{tag}")
        try:
            link_path, target = hf_link.link(name, repo, pattern)
            print(f"    {link_path} -> {target}")
        except Exception as ex:  # keep going on individual failures
            print(f"    ERROR: {ex}", file=sys.stderr)
            failures += 1

    _prune_detached()
    ok = total - failures
    print(f"Done — {ok}/{total} linked." + (f" {failures} failed." if failures else ""))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
