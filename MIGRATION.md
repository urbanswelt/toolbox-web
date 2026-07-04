# Migrating toolbox-web to a new machine

This app has been made largely self-contained: everything it needs to *run* lives
inside this folder. A few things are **machine-local data** that are deliberately
*not* bundled — they're re-downloaded or regenerated on the new machine (see
[What is NOT bundled](#what-is-not-bundled)).

---

## Folder layout (what travels with the app)

```
toolbox-web/
├── app.py                     # the Flask app
├── pyproject.toml, uv.lock    # dependencies + locked versions (incl. the `hf` CLI)
├── .python-version            # pins Python 3.14
├── .env.example               # documented config template (committed)
├── .env                       # local config — NOT transferred (gitignored)
├── .gitignore
├── requirements.txt           # pip fallback, exported from uv.lock
├── templates/  utils/         # web UI assets
├── config/                    # ALL configuration
│   ├── commands.yaml          #   toolbox commands, host commands, toolbox_repos
│   ├── models.yaml            #   curated model list (data; sync-models reads it)
│   ├── llama-models.ini       #   llama.cpp presets
│   ├── llama-coding-models.ini
│   └── llama-keys.txt         #   ⚠ SECRET (api key) — chmod 600, gitignored
├── scripts/                   # helper scripts (bundled; run via the project venv)
│   ├── install.sh             #   one-shot installer (uv sync + systemd)
│   ├── stop-server.sh         #   graceful llama/vllm shutdown
│   ├── hf_check_updates.py    #   model update checker (huggingface_hub)
│   ├── sync_models.py         #   download+link the whole list, then prune
│   ├── hf_link.py             #   snapshot_download + model-store symlink
│   └── drop_model.py          #   remove a cached model + its symlinks
├── toolbox-web.service        # systemd user unit (runs `uv run flask`)
├── toolbox-web@.service       # templated variant
└── toolbox-web-watch.path/.service   # auto-restart on app.py/index.html change
```

---

## Prerequisites on the new machine

Install these first (host-level, on `PATH`):

| Tool | Why | Install |
|---|---|---|
| **uv** | manages Python 3.14 + all app deps | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| **tmux** | session backend (sessions survive reload/reboot) | `sudo dnf install tmux` |
| **podman + toolbox** | the containers commands run in | `sudo dnf install podman toolbox` |
| **git** | the update manager pulls the toolbox repos | `sudo dnf install git` |

> **No host-level `hf` (or `curl`/`jq`) needed.** All Hugging Face operations —
> download/link (`hf_link.py`), delete (`drop_model.py`), sync (`sync_models.py`),
> and the update checker (`hf_check_updates.py`) — are Python using the
> `huggingface_hub` library from the project `.venv`. They're run with the venv
> interpreter directly, so nothing HF-related has to be installed on the host.

### Required shell environment (`~/.bashrc`)

The app reads Hugging Face settings from your **login shell**: it resolves the
cache dir and runs host commands via `bash -lc`, which sources `~/.bashrc` (the
systemd service has no such env of its own). Reproduce these on the new machine —
they're **host-wide** (your toolboxes, `~/run_benchmarks.sh`, and the `~/models`
symlink store all share the same cache):

```bash
# ~/.bashrc
export HF_HOME=$HOME/hf-cache                    # model cache (~/models symlinks point into $HF_HOME/hub)
export HF_HUB_ENABLE_HF_TRANSFER=1               # fast downloads
export HF_XET_HIGH_PERFORMANCE=1                 # xet acceleration
export HF_XET_RECONSTRUCTION_DOWNLOAD_BUFFER=64mb
export HF_XET_RECONSTRUCTION_DOWNLOAD_SIZE=64mb
```

Keep these in `~/.bashrc`, **not** the app's `.env`: they're host-wide (used well
beyond toolbox-web), and host commands run inside tmux sessions that only reliably
inherit env from `.bashrc` — putting them in `.env` would risk downloads landing
in the wrong cache.

### Authentication (gated / private models)

Public models download anonymously; gated ones (Llama, Gemma, …) need your Hugging
Face token. Pick one:

- **Set `HF_TOKEN=hf_…`** in `~/.bashrc` (next to the vars above) — simplest; both
  the app and `huggingface_hub` check it first, no login step needed.
- **Log in once.** The host `hf` CLI is no longer installed, so run it through uv,
  with `HF_HOME` already exported so the token lands where the library looks:

```bash
source ~/.bashrc                            # ensure HF_HOME is set first
uv run --with huggingface_hub hf auth login
```

That writes `$HF_HOME/token` and `$HF_HOME/stored_tokens` (e.g. `~/hf-cache/token`).
`huggingface_hub` reads the token from **`$HF_HOME/token`**, so `HF_HOME` must be set
at login time — otherwise it lands in `~/.cache/huggingface` and the app won't find
it. The token is a **secret** (like `config/llama-keys.txt`): prefer re-logging-in on
the new machine over copying the file around.

---

## Migration steps

### 1. Copy the app folder
Transfer the whole `toolbox-web/` folder, **excluding** machine-specific dirs:

```bash
rsync -a --exclude='.venv' --exclude='__pycache__' --exclude='logs/*.log' \
      toolbox-web/  newhost:~/toolbox-web/
```

`.venv/` is intentionally excluded — `uv` rebuilds it on the new host.

### 2. Transfer the secret separately (it's gitignored / may be excluded)
`config/llama-keys.txt` holds an API key. Copy it over a secure channel and lock it down:

```bash
scp config/llama-keys.txt newhost:~/toolbox-web/config/
ssh newhost 'chmod 600 ~/toolbox-web/config/llama-keys.txt'
```

### 3. Install + start the service
```bash
cd ~/toolbox-web
bash scripts/install.sh
```
This runs `uv sync` (creates `.venv` on Python 3.14), seeds `.env` from
`.env.example` if absent, installs + enables the systemd **user** service
(`uv run flask`), and enables linger.

### 4. Configure (optional)
Edit `~/toolbox-web/.env` — defaults to `0.0.0.0:5000`. Set `FLASK_RUN_HOST=127.0.0.1`
to restrict to localhost, change `FLASK_RUN_PORT`, set `TOOLBOX_WEB_TOKEN`, etc.
See `.env.example` for every knob. Then `systemctl --user restart toolbox-web`.

### 5. Rebuild the machine-local data (below)

---

## What is NOT bundled

These are regenerated/re-downloaded on the new machine, not carried over:

| Item | Location | How to restore |
|---|---|---|
| **Model blobs** | `~/.cache/huggingface` (HF cache) | re-downloaded by `sync-models` |
| **Model symlink store** | `~/models/` | rebuilt by `hf-link` when `sync-models` runs |
| **Toolbox source repos** | `~/github/amd-strix-halo-*` | `git clone` them, then `./refresh-*.sh` (paths in `config/commands.yaml` under `toolbox_repos:`) |
| **Toolboxes (containers)** | podman | created from the toolbox repos' refresh scripts |

### Rebuild the models
```bash
cd ~/toolbox-web
.venv/bin/python scripts/sync_models.py   # downloads everything in config/models.yaml + rebuilds ~/models symlinks
```
> The HF helpers (`sync_models.py`, `hf_link.py`, `drop_model.py`,
> `hf_check_updates.py`) are pure Python using the bundled `huggingface_hub`, so
> they need **no `hf` on PATH** — run them with the project `.venv` interpreter
> (the app does this automatically). Edit the curated list in `config/models.yaml`.

### Re-clone the toolbox repos
Paths/commands live in `config/commands.yaml` under `toolbox_repos:` (using `~`,
so they're user-portable). Clone each into `~/github/`, then use the in-app
**Update manager** (or run the listed `update` command) to build the toolboxes.

---

## Verify

```bash
systemctl --user status toolbox-web        # active (running), MainPID = uv
curl -fsS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:5000/   # 200
ss -ltnp | grep :5000                       # bound to the .env host/port
```

Open `http://<new-host-ip>:5000`. If unreachable from other machines, open the
firewall: `sudo firewall-cmd --add-port=5000/tcp --permanent && sudo firewall-cmd --reload`.

---

## Notes
- The whole stack is **uv-managed and pinned** (`pyproject.toml` + `uv.lock`,
  Python 3.14). `uv sync` reproduces the exact environment.
- `commands.yaml` is **hot-reloaded** — edit it (in the IDE or the in-app editor)
  without restarting. App code changes (`app.py`, `templates/index.html`) trigger
  an auto-restart via the `toolbox-web-watch.path` unit.
- Never commit/share `config/llama-keys.txt` or `.env` (both gitignored).
