"""M7.1/M7.3 AC: hello-module is discovered, mounted, authed, and emits."""

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


def test_manifest_lists_hello_module(client):
    mods = client.get("/modules", headers=AUTH).json()
    hello = next(m for m in mods if m["id"] == "hello-module")
    assert hello["panel"] == "hello-module"
    assert "log" in hello["eventTypes"]


def test_module_route_mounted_and_authed(client):
    assert client.get("/modules/hello-module/hello").status_code == 401
    r = client.get("/modules/hello-module/hello", headers=AUTH)
    assert r.status_code == 200
    assert r.json()["module"] == "hello-module"


def test_wave_emits_on_bus(client):
    with client.websocket_connect("/ws/events?token=sekrit") as ws:
        assert ws.receive_json()["type"] == "log"  # connect banner
        assert client.post("/modules/hello-module/wave", headers=AUTH).json() == {
            "waved": True
        }
        evt = ws.receive_json()
        assert evt["source"] == "hello-module"
        assert "wave" in evt["line"]
