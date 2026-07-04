"""M4.4 AC: unauthenticated requests rejected; valid token accepted."""

import pytest
from fastapi.testclient import TestClient


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


def test_health_open(client):
    assert client.get("/health").status_code == 200


def test_rest_requires_token(client):
    assert client.get("/graph").status_code == 401
    assert client.get("/graph", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/graph", headers={"Authorization": "Bearer sekrit"}).status_code == 200


def test_ws_requires_token(client):
    from starlette.websockets import WebSocketDisconnect as WsClosed

    with pytest.raises(WsClosed):
        with client.websocket_connect("/ws/events") as ws:
            ws.receive_json()

    with client.websocket_connect("/ws/events?token=sekrit") as ws:
        assert ws.receive_json()["type"] == "log"
