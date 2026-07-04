"""WS event bus (M4.3 skeleton) — fan out VaultEvents to all connected clients."""

from __future__ import annotations

import asyncio

from fastapi import WebSocket

from .events import VaultEvent


class EventBus:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)

    async def emit(self, event: VaultEvent) -> None:
        payload = event.model_dump(exclude_none=True)
        async with self._lock:
            clients = list(self._clients)
        for ws in clients:
            try:
                await ws.send_json(payload)
            except Exception:
                await self.disconnect(ws)


bus = EventBus()
