"""Hermes API entrypoint (M4 skeleton; grows via the module registry, M7)."""

import time

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from vault_indexer.graph import build_graph

from .bus import bus
from .config import settings
from .events import LogEvent
from .modules import registry

app = FastAPI(title="VAULT Hermes API", version="0.1.0")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "vault": str(settings.vault_path)}


@app.get("/graph")
async def graph() -> dict:
    """M2.1/M4.1 — vault as {nodes, links} for the 3D graph."""
    return build_graph(settings.vault_path)


@app.get("/modules")
async def modules() -> list[dict]:
    return registry.manifest()


@app.websocket("/ws/events")
async def ws_events(ws: WebSocket) -> None:
    await bus.connect(ws)
    try:
        await bus.emit(
            LogEvent(
                ts=time.time(), source="core", level="info", line="client connected"
            )
        )
        while True:
            # inbound messages are ignored for now; bus pushes outbound
            await ws.receive_text()
    except WebSocketDisconnect:
        await bus.disconnect(ws)


registry.mount_all(app)
