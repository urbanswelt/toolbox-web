#!/usr/bin/env python3
"""
toolbox-web — Web interface for Podman toolboxes with tmux backend.
Each command runs in a named tmux session. Browser can disconnect and
reconnect at any time; the session (and its scrollback) persists.

This file is just the entrypoint: `flask --app app run` (and `python app.py`)
both pick up the `app` object below. All logic lives in the toolbox_web package,
split by feature — see toolbox_web/__init__.py for the wiring.
"""

import os

from toolbox_web import create_app

app = create_app()

if __name__ == "__main__":
    # Mirrors the `flask run` knobs so `python app.py` honors the same .env.
    app.run(
        host=os.environ.get("FLASK_RUN_HOST", "127.0.0.1"),
        port=int(os.environ.get("FLASK_RUN_PORT", "5000")),
        debug=False,
        threaded=True,
    )
