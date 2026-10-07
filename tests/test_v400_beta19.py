"""4.0.0-beta.19: local development (dev.py) keeps its data in the project, refuses unsafe settings, and live reload
stays out of the site's own pages unless dev.py adds it."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import dev  # noqa: E402
from f1tracker.app import create_app  # noqa: E402


@pytest.fixture
def local(monkeypatch):
    for name in dev.OUTSIDE + ["F1_TRACKER_DATA_DIR", "F1_TRACKER_ENV", "F1_TRACKER_TEST_SITE"]:
        monkeypatch.setenv(name, "")      # recorded, so dev.environment()'s changes are undone afterwards
        monkeypatch.delenv(name)
    monkeypatch.setattr(dev.sys, "version_info", (3, 11, 9))
    return monkeypatch


def test_defaults_are_local_and_never_send(local):
    dev.environment()
    import os
    assert Path(os.environ["F1_TRACKER_DATA_DIR"]) == dev.DEV_DATA
    assert os.environ["F1_TRACKER_TEST_SITE"] == "1" and os.environ["F1_TRACKER_ENV"] == "local"
    assert dev.check() == []


@pytest.mark.parametrize("name", ["RENDER", "SMTP_HOST", "SMTP_PASSWORD"])
def test_refuses_host_and_mail_settings(local, name):
    local.setenv(name, "x")
    dev.environment()
    assert any(name in p for p in dev.check())


def test_refuses_data_outside_the_project(local, tmp_path):
    local.setenv("LOCALAPPDATA", str(tmp_path))
    local.setenv("F1_TRACKER_DATA_DIR", str(tmp_path / "F1UniverseTracker"))
    dev.environment()
    assert any("desktop app" in p for p in dev.check())
    local.setenv("F1_TRACKER_DATA_DIR", str(tmp_path / "elsewhere"))
    assert any("outside this project" in p for p in dev.check())


def test_refuses_other_python(local):
    local.setattr(dev.sys, "version_info", (3, 13, 0))
    dev.environment()
    assert any("3.11" in p for p in dev.check())


def test_live_reload_only_with_dev(tmp_path):
    plain = create_app({"TESTING": True}).test_client()
    assert b"/__dev/livereload.js" not in plain.get("/setup").data
    assert plain.get("/__dev/livereload.js").status_code != 200

    app = create_app({"TESTING": True, "STATIC_FINGERPRINT_FRESH": True})
    dev.add_live_reload(app)
    client = app.test_client()
    assert b'<script src="/__dev/livereload.js"></script></body>' in client.get("/setup").data
    js = client.get("/__dev/livereload.js")
    assert js.status_code == 200 and b"EventSource" in js.data
    events = client.get("/__dev/events")
    assert events.mimetype == "text/event-stream"
    assert next(events.response).startswith(b"data: ")
    events.close()
