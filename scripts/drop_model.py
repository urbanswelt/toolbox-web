"""drop-model — remove a cached HF model and its model-store symlinks.

Usage: drop_model.py <repo-id>   (a leading "model/" is accepted)

Python port of the former bash `drop-model`. Uses huggingface_hub.scan_cache_dir
to delete the repo from the cache, so no `hf` CLI needs to be on PATH. Run with
the project .venv interpreter (app.py invokes it directly).
"""

import os
import sys

from huggingface_hub import scan_cache_dir


def models_dir() -> str:
    return os.environ.get("TOOLBOX_WEB_MODELS_DIR") or os.path.expanduser("~/models")


def _repo_cache_path(repo: str) -> str:
    """The on-disk cache folder for a model repo (CACHE/models--org--name)."""
    cache_root = os.environ.get("HF_HUB_CACHE") or os.path.join(
        os.environ.get("HF_HOME") or os.path.expanduser("~/.cache/huggingface"), "hub"
    )
    return os.path.join(cache_root, "models--" + repo.replace("/", "--"))


def main(argv: list[str]) -> int:
    if not argv or not argv[0]:
        print("usage: drop-model <repo-id>", file=sys.stderr)
        return 2
    repo = argv[0]
    if repo.startswith("model/"):  # accept "model/<repo>" or "<repo>"
        repo = repo[len("model/") :]

    cache_dir = _repo_cache_path(repo)

    # Remove any model-store symlink that resolves into this repo's cache folder.
    mdir = models_dir()
    try:
        for name in sorted(os.listdir(mdir)):
            p = os.path.join(mdir, name)
            if not os.path.islink(p):
                continue
            tgt = os.path.realpath(p)
            if tgt == cache_dir or tgt.startswith(cache_dir + os.sep):
                print(f"Removing symlink: {p}")
                os.remove(p)
    except FileNotFoundError:
        pass

    # Delete the repo (all its revisions) from the HF cache.
    info = scan_cache_dir()
    hashes = [
        rev.commit_hash
        for r in info.repos
        if r.repo_type == "model" and r.repo_id == repo
        for rev in r.revisions
    ]
    if not hashes:
        print(f"Not in cache: model/{repo} (symlinks cleaned).")
        return 0
    print(f"Deleting cache: model/{repo}")
    info.delete_revisions(*hashes).execute()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
