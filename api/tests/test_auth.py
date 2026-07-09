"""M4.4 AC: unauthenticated requests rejected; valid token accepted."""

import pytest

from conftest import ASGIAppClient


@pytest.fixture
async def client(tmp_path, monkeypatch):
    from vault_api import config

    vault = tmp_path / "v"
    vault.mkdir()
    monkeypatch.setattr(config.settings, "vault_path", vault)
    monkeypatch.setattr(config.settings, "hermes_api_token", "sekrit")

    from vault_api.main import app

    async with ASGIAppClient(app) as c:
        yield c


@pytest.mark.asyncio
async def test_health_open(client):
    assert (await client.get("/health")).status_code == 200


@pytest.mark.asyncio
async def test_rest_requires_token(client):
    assert (await client.get("/graph")).status_code == 401
    assert (
        await client.get("/graph", headers={"Authorization": "Bearer wrong"})
    ).status_code == 401
    assert (
        await client.get("/graph", headers={"Authorization": "Bearer sekrit"})
    ).status_code == 200


@pytest.mark.asyncio
async def test_ws_requires_token(client):
    from starlette.websockets import WebSocketDisconnect as WsClosed

    with pytest.raises(WsClosed):
        async with client.websocket_connect("/ws/events") as ws:
            await ws.receive_json()

    async with client.websocket_connect("/ws/events?token=sekrit") as ws:
        assert (await ws.receive_json())["type"] == "log"


@pytest.mark.asyncio
async def test_cors_preflight_and_origin(client):
    """Regression: the webview origin must pass CORS or the graph never loads."""
    r = await client.options(
        "/graph",
        headers={
            "Origin": "http://localhost:1420",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:1420"
    r = await client.get(
        "/graph",
        headers={
            "Origin": "http://localhost:1420",
            "Authorization": "Bearer sekrit",
        },
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:1420"
