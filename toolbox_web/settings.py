"""Central configuration: env-derived paths, tokens, and shared constants.

Everything here is import-only (no sibling imports), so every other module can
depend on it without risking a circular import. Reading os.environ happens once,
at import time, after .env is loaded below.
"""

import os
import sys

from dotenv import load_dotenv

# The package lives one directory below the project root; resolve the root so the
# default paths below match the original single-file app (which used the dir of
# app.py at the repo root).
_HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(_HERE)

# Load .env from the project root before any TOOLBOX_WEB_* / FLASK_* settings are
# read below. Harmless if the file is absent. The `flask` CLI also auto-loads it
# (python-dotenv is a dependency); this explicit call also covers `python app.py`.
# All available knobs are documented in .env.example.
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

# ── Output logging ─────────────────────────────────────────────────────────────
# Each session's raw output is teed to a file via `tmux pipe-pane`. The stream
# endpoint tails that file by byte offset, which is append-only and unbounded —
# unlike capture-pane, which only exposes a sliding ~2000-line window.
LOG_DIR = os.environ.get(
    "TOOLBOX_WEB_LOG_DIR",
    os.path.join(PROJECT_ROOT, "logs"),
)
os.makedirs(LOG_DIR, exist_ok=True)

# How much trailing log to backfill on a fresh (non-resuming) connection.
LOG_BACKLOG_BYTES = 256 * 1024
# Delete log files untouched for this long (housekeeping).
LOG_MAX_AGE_SECONDS = 3 * 24 * 3600

# ── Command sets per toolbox category (loaded from commands.yaml) ──────────────
# The config file is hot-reloaded: edits take effect on the next request, with
# no service restart. See commands.yaml for the schema.
CONFIG_PATH = os.environ.get(
    "TOOLBOX_WEB_CONFIG",
    os.path.join(PROJECT_ROOT, "config", "commands.yaml"),
)

# Bundled helper scripts live in toolbox-web/scripts/ so they travel with the app.
SCRIPTS_DIR = os.path.join(PROJECT_ROOT, "scripts")
# The Python that runs the bundled HF scripts — this very interpreter, i.e. the
# project .venv (the app runs under `uv run flask`). No `hf` on PATH required.
VENV_PYTHON = sys.executable

# Optional shared secret. If set, the config-WRITE endpoint requires it (sent as
# the X-Toolbox-Token header). Reads and command execution are unaffected — they
# already have no auth — so this only narrows who can rewrite the command file.
CONFIG_TOKEN = os.environ.get("TOOLBOX_WEB_TOKEN", "").strip()

# Files the in-browser editor may open: commands.yaml plus the llama.cpp preset
# .ini files in the models dir. Reads/writes are restricted to this allowlist —
# arbitrary paths are never accepted.
MODELS_DIR = os.environ.get("TOOLBOX_WEB_MODELS_DIR", os.path.expanduser("~/models"))

# llama.cpp preset .ini files live bundled with the app (toolbox-web/config/) so
# they travel with it. MODELS_DIR stays the model symlink store that hf-link
# populates and the app scans for .gguf files.
PRESETS_DIR = os.environ.get(
    "TOOLBOX_WEB_PRESETS_DIR",
    os.path.join(PROJECT_ROOT, "config"),
)

# Curated model list. The data lives in config/models.yaml — the app reads it for
# managed entries and appends to it on download. scripts/sync_models.py downloads
# and links the whole list (run with VENV_PYTHON).
MODELS_LIST_PATH = os.environ.get(
    "TOOLBOX_WEB_MODELS_LIST",
    os.path.join(PROJECT_ROOT, "config", "models.yaml"),
)
SYNC_MODELS_SCRIPT = os.environ.get(
    "TOOLBOX_WEB_SYNC_MODELS", os.path.join(SCRIPTS_DIR, "sync_models.py")
)

# Toolbox source repos for the update manager. Each entry: {name, path, update}.
# Primary source is the `toolbox_repos:` list in commands.yaml; this portable
# default (paths under ~) is only the fallback if that section is absent.
DEFAULT_TOOLBOX_REPOS = [
    {
        "name": "comfyui-toolboxes",
        "path": os.path.expanduser("~/github/amd-strix-halo-comfyui-toolboxes"),
        "update": "git pull && ./refresh-toolbox.sh latest",
    },
    {
        "name": "strix-halo-toolboxes",
        "path": os.path.expanduser("~/github/amd-strix-halo-toolboxes"),
        "update": "git pull && ./refresh-toolboxes.sh all",
    },
    {
        "name": "vllm-toolboxes",
        "path": os.path.expanduser("~/github/amd-strix-halo-vllm-toolboxes"),
        "update": (
            "git pull && ./refresh_toolbox.sh latest && "
            "sed 's/^TOOLBOX_NAME=.*/TOOLBOX_NAME=\"vllm-dev\"/' "
            "refresh_toolbox.sh | bash -s -- dev"
        ),
    },
]

# Extra individual files the editor may open (beyond commands.yaml + model .ini's).
EXTRA_EDITABLE = [
    {"id": "models.yaml", "path": MODELS_LIST_PATH, "type": "models"},
]

# Sentinel "container" for commands that run directly on the host (not in a
# toolbox) — e.g. Hugging Face cache checks and model sync.
HOST_ID = "__host__"

# Filesystem reported in the footer — defaults to home (where models/HF cache live).
DISK_PATH = os.environ.get("TOOLBOX_WEB_DISK_PATH", os.path.expanduser("~"))
