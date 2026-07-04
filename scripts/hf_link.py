"""hf-link — download a Hugging Face repo and symlink it into the model store.

Usage: hf_link.py <local-name> <repo-id> [include-pattern]

Python port of the former bash `hf-link`. It uses the huggingface_hub library
directly (the project's uv-pinned copy), so no `hf` CLI needs to be on PATH.
Run with the project .venv interpreter (app.py invokes it directly). Honors
HF_HOME / HF_HUB_CACHE / HF_HUB_ENABLE_HF_TRANSFER from the environment, exactly
like the CLI did.
"""

import os
import sys

from huggingface_hub import snapshot_download


def models_dir() -> str:
    """Model symlink store — matches the app's MODELS_DIR (TOOLBOX_WEB_MODELS_DIR)."""
    return os.environ.get("TOOLBOX_WEB_MODELS_DIR") or os.path.expanduser("~/models")


def _resolve_target(snapshot: str, pattern: str) -> str:
    """Pick the symlink target: a pattern like "BF16/*" points at that subdir
    when it exists (what the .ini presets reference); otherwise the snapshot root."""
    if pattern.endswith("/*"):
        subdir = pattern[:-2]
        candidate = os.path.join(snapshot, subdir)
        if os.path.isdir(candidate):
            return candidate
    return snapshot


def link(name: str, repo: str, pattern: str = "") -> tuple[str, str]:
    """Download `repo` (optionally filtered by `pattern`) and point the model-store
    symlink `name` at it. Returns (link_path, target). Reusable by sync-models."""
    snapshot = snapshot_download(repo_id=repo, allow_patterns=pattern or None)
    target = _resolve_target(snapshot, pattern)
    if not os.path.isdir(target):
        raise FileNotFoundError(f"target does not exist: {target}")
    link_path = os.path.join(models_dir(), name)
    os.makedirs(os.path.dirname(link_path), exist_ok=True)
    if os.path.islink(link_path) or os.path.isfile(link_path):
        os.remove(link_path)  # replace, like `ln -sfn`
    os.symlink(target, link_path)
    return link_path, target


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(
            "usage: hf-link <local-name> <repo-id> [include-pattern]", file=sys.stderr
        )
        return 2
    name, repo = argv[0], argv[1]
    pattern = argv[2] if len(argv) > 2 else ""
    try:
        link_path, target = link(name, repo, pattern)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    print(f"{link_path} -> {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
