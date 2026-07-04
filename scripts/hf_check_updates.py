"""hf-check-updates — report which cached HF models are outdated vs the Hub.

Python port of the former hf_check_updates.sh. Uses huggingface_hub
(scan_cache_dir + HfApi) instead of the `hf` CLI + curl + jq, so it needs none
of those on PATH. Read-only: it downloads nothing. Run with the project .venv
interpreter (the "Check model updates" host command invokes it directly).
"""

import os
import sys

from huggingface_hub import HfApi, scan_cache_dir
from huggingface_hub.errors import CacheNotFound

RED = "\033[0;31m"
YELLOW = "\033[1;33m"
GREEN = "\033[0;32m"
CYAN = "\033[0;36m"
BOLD = "\033[1m"
RESET = "\033[0m"
BAR = "═" * 56


def _token() -> str:
    """HF token: HF_TOKEN env, then the stored token file, else anonymous."""
    tok = os.environ.get("HF_TOKEN", "").strip()
    if tok:
        return tok
    hf_home = os.environ.get("HF_HOME") or os.path.expanduser("~/.cache/huggingface")
    try:
        with open(os.path.join(hf_home, "token"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _cache_dir() -> str:
    """The HF hub cache dir, resolved like the CLI: HF_HUB_CACHE, else HF_HOME/hub."""
    hub = os.environ.get("HF_HUB_CACHE")
    if hub:
        return hub
    hf_home = os.environ.get("HF_HOME") or os.path.expanduser("~/.cache/huggingface")
    return os.path.join(hf_home, "hub")


def _gb(nbytes) -> str:
    return f"{nbytes / 1073741824:.2f} GB"


def _show_files(api: HfApi, repo_id: str) -> None:
    """List the files in the latest remote snapshot (LFS sizes when available)."""
    print(f"   {CYAN}Files in latest remote snapshot:{RESET}")
    try:
        sibs = api.model_info(repo_id, files_metadata=True).siblings or []
    except Exception:
        sibs = []
    for s in sibs[:40]:  # cap so huge GGUF repos stay readable
        if s.lfs is not None:
            tag = f"  ({_gb(s.size)})" if getattr(s, "size", None) else ""
            print(f"     [LFS] {s.rfilename}{tag}")
        else:
            print(f"           {s.rfilename}")
    print(f"   {CYAN}Total files in repo: {BOLD}{len(sibs)}{RESET}")


def main() -> int:
    token = _token()
    print()
    print(f"{BOLD}{BAR}{RESET}")
    print(f"{BOLD}  Hugging Face Cache Update Checker{RESET}")
    print(f"{BOLD}{BAR}{RESET}")
    try:
        info = scan_cache_dir()
    except CacheNotFound:
        print(f"  {YELLOW}No cache found — nothing to check.{RESET}")
        return 0
    print(f"  Cache dir : {_cache_dir()}")
    print(
        "  Auth      : "
        + ("token found ✓" if token else "anonymous — set HF_TOKEN for gated models")
    )
    print()

    repos = sorted(
        (r for r in info.repos if r.repo_type == "model"),
        key=lambda r: r.repo_id.lower(),
    )
    if not repos:
        print(f"{YELLOW}No models found in cache.{RESET}")
        return 0

    api = HfApi(token=token or None)
    up_to_date = outdated = errors = 0

    for repo in repos:
        rid = repo.repo_id
        print(f"{BOLD}▶  {rid}{RESET}")

        rev = next((v for v in repo.revisions if "main" in v.refs), None)
        local_hash = rev.commit_hash if rev else ""
        if not local_hash:
            print(f"   {YELLOW}⚠  No local 'main' ref — skipping{RESET}\n")
            errors += 1
            continue
        print(f"   Local  SHA : {local_hash[:12]}…")

        try:
            mi = api.model_info(rid)
        except Exception as e:
            print(
                f"   {YELLOW}⚠  Could not reach HF API ({type(e).__name__}) — skipping{RESET}\n"
            )
            errors += 1
            continue

        remote_hash = mi.sha or ""
        if not remote_hash:
            print(f"   {YELLOW}⚠  No remote SHA — skipping{RESET}\n")
            errors += 1
            continue
        lm = mi.last_modified.strftime("%Y-%m-%d") if mi.last_modified else "unknown"
        print(f"   Remote SHA : {remote_hash[:12]}…   (last modified: {lm})")

        if local_hash == remote_hash:
            print(f"   {GREEN}✅  Up to date{RESET}\n")
            up_to_date += 1
        else:
            print(f"   {RED}⚠️  OUTDATED{RESET} — remote has new commits")
            outdated += 1
            _show_files(api, rid)
            print()
            print(
                f"   {CYAN}To update: re-pull it from the model manager (↻), "
                f"or run Sync / update models.{RESET}\n"
            )

    print(f"{BOLD}{BAR}{RESET}")
    print(f"  {GREEN}Up to date : {up_to_date}{RESET}")
    print(f"  {RED}Outdated   : {outdated}{RESET}")
    if errors:
        print(f"  {YELLOW}Skipped    : {errors}{RESET}")
    print(f"{BOLD}{BAR}{RESET}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
