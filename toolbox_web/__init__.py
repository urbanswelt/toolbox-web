"""toolbox-web application package.

`create_app()` is the Flask application factory: it wires the blueprints from
each feature module together and starts the two background daemon threads (the
session/container reaper and the system-stats sampler). The thin top-level
`app.py` calls this so `flask --app app run` keeps working unchanged.
"""

import os
import threading

from flask import Flask

from .settings import PROJECT_ROOT

# Guard so the background threads start exactly once even if create_app() is
# called more than once (e.g. tests).
_threads_started = False
_threads_lock = threading.Lock()


def _start_background_threads() -> None:
    global _threads_started
    with _threads_lock:
        if _threads_started:
            return
        # Imported here (not at module top) so importing the package for, say, a
        # unit test of a pure helper doesn't spin up the reaper/sampler threads.
        from .sessions import _session_watcher
        from .stats import _stats_sampler

        threading.Thread(target=_session_watcher, daemon=True).start()
        threading.Thread(target=_stats_sampler, daemon=True).start()
        _threads_started = True


def create_app() -> Flask:
    # Templates and static assets live at the repo root, not inside the package.
    app = Flask(
        __name__,
        template_folder=os.path.join(PROJECT_ROOT, "templates"),
        static_folder=os.path.join(PROJECT_ROOT, "static"),
    )

    from . import commands, configfiles, models, presets, stats, terminal, toolboxes, views

    for module in (
        views,
        configfiles,
        commands,
        presets,
        models,
        toolboxes,
        stats,
        terminal,
    ):
        app.register_blueprint(module.bp)

    _start_background_threads()
    return app
