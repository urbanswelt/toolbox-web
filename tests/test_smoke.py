"""Smoke test: the app boots and serves its core pages without any live config.

Deliberately points the config paths at an empty temp dir so the test does not
depend on the git-ignored files under config/ (a fresh clone / CI has only the
*.example files). It also needs no tmux/podman — the checked routes render the
page and read config, they don't shell out. This is the check that gates
dependency-update PRs: if a bumped package breaks an import or a Flask/Werkzeug
API, booting the app here fails.
"""

import os

import pytest


@pytest.fixture()
def client(tmp_path):
    # Isolate from the real (git-ignored) config so the boot is self-contained.
    os.environ["TOOLBOX_WEB_CONFIG"] = str(tmp_path / "commands.yaml")
    os.environ["TOOLBOX_WEB_PRESETS_DIR"] = str(tmp_path)
    os.environ["TOOLBOX_WEB_MODELS_LIST"] = str(tmp_path / "models.yaml")

    from toolbox_web import create_app

    app = create_app()
    app.config.update(TESTING=True)
    return app.test_client()


def test_index_serves(client):
    """The main page renders (this also exercises the static asset URLs)."""
    r = client.get("/")
    assert r.status_code == 200
    assert b"/static/" in r.data  # the extracted css/js are referenced


def test_config_files_endpoint(client):
    """The editable-files listing responds even with no config on disk."""
    r = client.get("/api/config/files")
    assert r.status_code == 200


def test_commands_structured_endpoint(client):
    """Structured command view degrades gracefully when commands.yaml is absent."""
    r = client.get("/api/commands/structured")
    assert r.status_code == 200
