import asyncio
import json
from urllib.parse import urlsplit

import httpx
from starlette.websockets import WebSocketDisconnect


class ASGIWebSocketSession:
    def __init__(self, app, path: str, headers: dict[str, str] | None = None):
        self.app = app
        self.path = path
        self.headers = headers or {}
        self._in: asyncio.Queue[dict] = asyncio.Queue()
        self._out: asyncio.Queue[dict] = asyncio.Queue()
        self._task: asyncio.Task | None = None

    async def __aenter__(self):
        parsed = urlsplit(self.path)
        scope = {
            "type": "websocket",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "scheme": "ws",
            "path": parsed.path,
            "raw_path": parsed.path.encode(),
            "query_string": parsed.query.encode(),
            "headers": [
                (k.lower().encode(), v.encode()) for k, v in self.headers.items()
            ],
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
            "subprotocols": [],
        }
        await self._in.put({"type": "websocket.connect"})
        self._task = asyncio.create_task(self.app(scope, self._receive, self._send))
        msg = await asyncio.wait_for(self._out.get(), timeout=5)
        if msg["type"] == "websocket.close":
            raise WebSocketDisconnect(msg.get("code", 1000))
        assert msg["type"] == "websocket.accept"
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self._in.put({"type": "websocket.disconnect", "code": 1000})
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=2)
            except asyncio.TimeoutError:
                self._task.cancel()
                await asyncio.gather(self._task, return_exceptions=True)

    async def _receive(self) -> dict:
        return await self._in.get()

    async def _send(self, message: dict) -> None:
        await self._out.put(message)

    async def receive_json(self, timeout: float = 5.0) -> dict:
        while True:
            msg = await asyncio.wait_for(self._out.get(), timeout=timeout)
            if msg["type"] == "websocket.close":
                raise WebSocketDisconnect(msg.get("code", 1000))
            if msg["type"] == "websocket.send":
                if "text" in msg:
                    return json.loads(msg["text"])
                return json.loads(msg["bytes"].decode())


class ASGIAppClient:
    def __init__(self, app):
        self.app = app
        self._lifespan = None
        self._http: httpx.AsyncClient | None = None

    async def __aenter__(self):
        self._lifespan = self.app.router.lifespan_context(self.app)
        await self._lifespan.__aenter__()
        transport = httpx.ASGITransport(app=self.app)
        self._http = httpx.AsyncClient(transport=transport, base_url="http://testserver")
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._http is not None:
            await self._http.aclose()
        if self._lifespan is not None:
            await self._lifespan.__aexit__(exc_type, exc, tb)
        await asyncio.get_running_loop().shutdown_default_executor()

    async def get(self, *args, **kwargs):
        assert self._http is not None
        return await self._http.get(*args, **kwargs)

    async def post(self, *args, **kwargs):
        assert self._http is not None
        return await self._http.post(*args, **kwargs)

    async def options(self, *args, **kwargs):
        assert self._http is not None
        return await self._http.options(*args, **kwargs)

    def websocket_connect(
        self, path: str, headers: dict[str, str] | None = None
    ) -> ASGIWebSocketSession:
        return ASGIWebSocketSession(self.app, path, headers=headers)
