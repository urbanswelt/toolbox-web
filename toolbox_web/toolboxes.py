"""Toolbox containers and their source repos (the update manager).

Two related concerns: enumerating the podman toolbox containers, and the git
status / update commands for the source repos that build them.
"""

import os
import shlex
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Blueprint, jsonify, request

from .configfiles import get_commands_for, get_toolbox_repos
from .sessions import _session_name, _start_host, tmux_list_sessions
from .settings import CONFIG_TOKEN

bp = Blueprint("toolboxes", __name__)


def list_toolboxes() -> list[dict]:
    # \x1f (unit separator) delimits fields so image names / statuses can't clash.
    fmt = (
        "{{.ID}}\x1f{{.Names}}\x1f{{.Status}}\x1f{{.Image}}\x1f"
        '{{index .Labels "org.opencontainers.image.source"}}'
    )
    try:
        result = subprocess.run(
            [
                "podman",
                "ps",
                "-a",
                "--filter",
                "label=com.github.containers.toolbox=true",
                "--format",
                fmt,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        boxes = []
        for line in result.stdout.strip().splitlines():
            if not line.strip():
                continue
            parts = line.split("\x1f")
            if len(parts) >= 5:
                cid, name, status, image, source = (p.strip() for p in parts[:5])
                boxes.append(
                    {
                        "id": cid,
                        "name": name,
                        "status": status,
                        "running": status.lower().startswith("up"),
                        "image": image,
                        "source": source,
                    }
                )
        return boxes
    except Exception:
        return []


def _repo_for_container(image: str, source: str, repos: list[dict]) -> str | None:
    """Map a toolbox container to the source repo that builds it (by name)."""
    src_base = source.rstrip("/").split("/")[-1] if source else ""
    # Prefer the image-source label (exact repo folder name), then fall back to
    # the image reference containing the repo's directory name.
    for r in repos:
        if src_base and src_base == os.path.basename(r["path"].rstrip("/")):
            return r["name"]
    for r in repos:
        rb = os.path.basename(r["path"].rstrip("/"))
        if rb and rb in image:
            return r["name"]
    return None


def _git(path: str, *args: str, timeout: int = 60):
    return subprocess.run(
        ["git", "-C", path, *args], capture_output=True, text=True, timeout=timeout
    )


def _toolbox_status(repo: dict, do_fetch: bool) -> dict:
    """Local (and optionally fetched) git status of one toolbox repo.

    status: uptodate | update | unknown | missing.  `behind`/`ahead` are commit
    counts vs the upstream tracking branch (meaningful only after a fetch).
    """
    path = repo["path"]
    info = {
        "name": repo["name"],
        "path": path,
        "branch": "",
        "ahead": 0,
        "behind": 0,
        "status": "unknown",
    }
    if not os.path.isdir(os.path.join(path, ".git")):
        info["status"] = "missing"
        return info
    if do_fetch:
        try:
            _git(path, "fetch", "--quiet", timeout=120)
        except Exception:
            pass
    br = _git(path, "rev-parse", "--abbrev-ref", "HEAD")
    info["branch"] = br.stdout.strip() if br.returncode == 0 else "?"
    cnt = _git(path, "rev-list", "--left-right", "--count", "HEAD...@{u}")
    if cnt.returncode == 0 and cnt.stdout.strip():
        try:
            ahead, behind = (int(x) for x in cnt.stdout.split())
            info["ahead"], info["behind"] = ahead, behind
            info["status"] = "update" if behind > 0 else "uptodate"
        except ValueError:
            info["status"] = "unknown"  # detached / no upstream
    return info


def _image_status(image: str) -> dict:
    """Compare a local toolbox image's digest with its registry tag's current one.

    status: update | uptodate | unknown.  A digest mismatch means the registry
    serves a newer image for that tag than the one pulled locally.  `unknown`
    when either digest can't be read (local-only image, registry unreachable…).
    """
    info = {"image": image, "status": "unknown", "local": "", "remote": ""}
    try:
        loc = subprocess.run(
            ["podman", "image", "inspect", image, "--format", "{{.Digest}}"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if loc.returncode == 0:
            info["local"] = loc.stdout.strip()
    except Exception:
        pass
    try:
        rem = subprocess.run(
            ["skopeo", "inspect", "--no-tags", "--format", "{{.Digest}}",
             f"docker://{image}"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if rem.returncode == 0:
            info["remote"] = rem.stdout.strip()
    except Exception:
        pass
    if info["local"] and info["remote"]:
        info["status"] = "update" if info["local"] != info["remote"] else "uptodate"
    return info


def _toolbox_update_cmd(repo: dict) -> str:
    """Shell to update one repo: cd into it, then run its update command."""
    return f"cd {shlex.quote(repo['path'])} && {repo['update']}"


@bp.route("/api/toolboxes")
def api_toolboxes():
    boxes = list_toolboxes()
    # Annotate with any live tmux session
    sessions = {s["name"]: s for s in tmux_list_sessions()}
    for b in boxes:
        cmds = get_commands_for(b["name"])
        active = []
        for c in cmds:
            sname = _session_name(b["name"], c["cmd"])
            if sname in sessions:
                active.append(sname)
        b["active_sessions"] = active
    return jsonify(boxes)


@bp.route("/api/toolbox-repos")
def api_toolbox_repos():
    """Configured repos (local git status) with their toolbox containers grouped."""
    repos = get_toolbox_repos()
    out = [_toolbox_status(r, do_fetch=False) for r in repos]

    by_repo: dict[str, list] = {r["name"]: [] for r in out}
    others: list[dict] = []
    for b in list_toolboxes():
        entry = {
            "name": b["name"],
            "status": b["status"],
            "running": b["running"],
            "image": b.get("image", ""),
        }
        rn = _repo_for_container(b.get("image", ""), b.get("source", ""), repos)
        (by_repo[rn] if rn in by_repo else others).append(entry)
    for o in out:
        o["containers"] = by_repo.get(o["name"], [])

    return jsonify(
        {"repos": out, "others": others, "token_required": bool(CONFIG_TOKEN)}
    )


@bp.route("/api/toolbox-check-updates", methods=["POST"])
def api_toolbox_check_updates():
    """Check repos (git fetch) and container images (registry digest), concurrently.

    Returns `results` (per-repo git status, keyed by repo name) and `images`
    (per-image digest status, keyed by image reference).
    """
    repos = get_toolbox_repos()
    images = sorted({b["image"] for b in list_toolboxes() if b.get("image")})
    results: dict[str, dict] = {}
    image_results: dict[str, dict] = {}
    if repos or images:
        with ThreadPoolExecutor(max_workers=6) as ex:
            git_futs = {ex.submit(_toolbox_status, r, True): r for r in repos}
            img_futs = {ex.submit(_image_status, im): im for im in images}
            for fut in as_completed(git_futs):
                try:
                    res = fut.result()
                except Exception:
                    r = git_futs[fut]
                    res = {
                        "name": r["name"],
                        "status": "unknown",
                        "branch": "",
                        "ahead": 0,
                        "behind": 0,
                    }
                results[res["name"]] = res
            for fut in as_completed(img_futs):
                try:
                    res = fut.result()
                except Exception:
                    res = {
                        "image": img_futs[fut],
                        "status": "unknown",
                        "local": "",
                        "remote": "",
                    }
                image_results[res["image"]] = res
    return jsonify({"results": results, "images": image_results})


@bp.route("/api/update-toolbox", methods=["POST"])
def api_update_toolbox():
    """Pull + refresh a single toolbox repo, streamed as a host session."""
    if CONFIG_TOKEN and request.headers.get("X-Toolbox-Token", "") != CONFIG_TOKEN:
        return jsonify({"error": "Invalid or missing token."}), 403
    name = (request.get_json(silent=True) or {}).get("name", "").strip()
    repo = next((r for r in get_toolbox_repos() if r["name"] == name), None)
    if not repo:
        return jsonify({"error": "Unknown toolbox repo."}), 400
    if not repo.get("update"):
        return jsonify({"error": "No update command configured for this repo."}), 400
    session = _start_host(_toolbox_update_cmd(repo))
    if not session:
        return jsonify({"error": "Failed to start update session."}), 500
    return jsonify({"session": session})


@bp.route("/api/update-toolboxes", methods=["POST"])
def api_update_toolboxes():
    """Pull + refresh every configured repo in order, streamed as one session."""
    if CONFIG_TOKEN and request.headers.get("X-Toolbox-Token", "") != CONFIG_TOKEN:
        return jsonify({"error": "Invalid or missing token."}), 403
    repos = [r for r in get_toolbox_repos() if r.get("update")]
    if not repos:
        return jsonify({"error": "No toolbox repos configured."}), 400
    segs = []
    for r in repos:
        segs.append(
            f'printf "\\n\\033[1m=== %s ===\\033[0m\\n" {shlex.quote(r["name"])}'
        )
        segs.append(_toolbox_update_cmd(r))
    session = _start_host(" && ".join(segs))
    if not session:
        return jsonify({"error": "Failed to start update session."}), 500
    return jsonify({"session": session})
