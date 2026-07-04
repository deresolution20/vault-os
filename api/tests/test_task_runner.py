"""task-runner module: run streams events; cancel kills the process group."""

import time

import pytest
from fastapi.testclient import TestClient

AUTH = {"Authorization": "Bearer sekrit"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    from vault_api import config

    vault = tmp_path / "v"
    vault.mkdir()
    monkeypatch.setattr(config.settings, "vault_path", vault)
    monkeypatch.setattr(config.settings, "hermes_api_token", "sekrit")

    from vault_api.main import app

    with TestClient(app) as c:
        yield c


def _drain_until(ws, wanted_type, task_id, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        evt = ws.receive_json()
        if evt.get("taskId") == task_id and evt["type"] == wanted_type:
            return evt
    raise AssertionError(f"never saw {wanted_type} for {task_id}")


def test_run_streams_and_completes(client):
    with client.websocket_connect("/ws/events?token=sekrit") as ws:
        ws.receive_json()  # banner
        r = client.post(
            "/modules/task-runner/run",
            headers=AUTH,
            json={"cmd": ["bash", "-c", "echo alpha; echo beta"],
                  "title": "echo test"},
        )
        assert r.status_code == 202
        tid = r.json()["taskId"]
        assert _drain_until(ws, "task_start", tid)
        log = _drain_until(ws, "log", tid)
        assert log["line"] in ("alpha", "beta")
        done = _drain_until(ws, "task_done", tid)
        assert done["status"] == "success"


def test_cancel_kills_process_group(client):
    with client.websocket_connect("/ws/events?token=sekrit") as ws:
        ws.receive_json()
        r = client.post(
            "/modules/task-runner/run",
            headers=AUTH,
            json={"cmd": ["bash", "-c", "sleep 60 & wait"],
                  "title": "long sleep"},
        )
        tid = r.json()["taskId"]
        _drain_until(ws, "task_start", tid)
        rc = client.post(f"/modules/task-runner/cancel/{tid}", headers=AUTH)
        assert rc.json()["cancelled"]
        done = _drain_until(ws, "task_done", tid)
        assert done["status"] == "cancelled"
    assert client.get("/modules/task-runner/running", headers=AUTH).json() == {
        "tasks": []
    }


def test_bad_command_400(client):
    r = client.post(
        "/modules/task-runner/run",
        headers=AUTH,
        json={"cmd": ["/nonexistent-binary-xyz"], "title": "boom"},
    )
    assert r.status_code == 400
