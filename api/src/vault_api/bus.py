"""WS event bus (M4.3 skeleton) — fan out VaultEvents to all connected clients."""

from __future__ import annotations

import asyncio

from fastapi import WebSocket

from .events import VaultEvent


class EventBus:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        # in-process subscribers (modules reacting to events, e.g. Plane sync)
        self._subscribers: list = []

    def subscribe(self, callback) -> None:
        """callback: async fn(VaultEvent) — errors are logged, never fatal."""
        self._subscribers.append(callback)

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
        for cb in self._subscribers:
            try:
                await cb(event)
            except Exception as e:  # a broken subscriber must not stop the bus
                print(f"[bus] subscriber error: {e}")


bus = EventBus()
