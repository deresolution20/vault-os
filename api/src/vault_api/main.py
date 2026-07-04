"""Hermes API entrypoint (M4; grows via the module registry, M7)."""

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from vault_indexer.graph import build_graph

from . import obsidian
from .auth import auth_required, require_ws_token
from .bus import bus
from .config import settings
from .events import LogEvent
from .modules import registry
from .rag import rag


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio

    from .watcher import watcher

    if not settings.hermes_api_token:
        print("[auth] WARNING: HERMES_API_TOKEN unset — auth disabled (loopback only)")
    watcher.start(asyncio.get_running_loop())
    yield
    watcher.stop()


app = FastAPI(title="VAULT Hermes API", version="0.1.0", lifespan=lifespan)

# The HUD webview is a different origin (vite dev / tauri://) than this API,
# so browser fetch() needs CORS. Local UI origins only — never "*".
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:1420",  # vite dev server (tauri dev)
        "tauri://localhost",  # bundled app (linux/mac)
        "http://tauri.localhost",  # bundled app (windows)
    ],
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.get("/health")
async def health() -> dict:
    """Unauthenticated liveness probe (no vault content exposed)."""
    return {"status": "ok"}


@app.get("/modules", dependencies=[auth_required])
async def modules() -> list[dict]:
    return registry.manifest()


@app.get("/graph", dependencies=[auth_required])
async def graph() -> dict:
    """M2.1/M4.1 — vault as {nodes, links} for the 3D graph."""
    return build_graph(settings.vault_path)


class RagQuery(BaseModel):
    query: str
    limit: int = 8


@app.post("/rag/query", dependencies=[auth_required])
async def rag_query(q: RagQuery) -> dict:
    """M2.2/M4.1 — semantic search over the vault (local embeddings only)."""
    results = await run_in_threadpool(rag().query, q.query, q.limit)
    return {"query": q.query, "results": results}


@app.post("/rag/reindex", dependencies=[auth_required])
async def rag_reindex() -> dict:
    """Full re-index; the M2.3 watcher handles incremental updates."""
    return await run_in_threadpool(rag().index_all)


class NoteCreate(BaseModel):
    path: str  # vault-relative, e.g. "Projects/VAULT.md"
    content: str


class NotePatch(BaseModel):
    content: str
    heading: str | None = None  # insert under this heading; None = append


@app.post("/notes", status_code=201, dependencies=[auth_required])
async def create_note(note: NoteCreate) -> dict:
    """M4.1/M4.2 — create/replace a note through the Obsidian write layer.

    The M2.3 watcher picks up the new file and emits node_update, so a write
    surfaces as a new graph node without extra wiring (PRD §7 'graph as hub').
    """
    try:
        await obsidian.write_note(note.path, note.content)
    except obsidian.ObsidianUnavailable as e:
        raise HTTPException(503, f"Obsidian write layer unavailable: {e}")
    return {"path": note.path, "written": True}


@app.patch("/notes/{path:path}", dependencies=[auth_required])
async def patch_note(path: str, patch: NotePatch) -> dict:
    try:
        if patch.heading:
            await obsidian.patch_note(path, patch.content, patch.heading)
        else:
            await obsidian.append_note(path, patch.content)
    except obsidian.ObsidianUnavailable as e:
        raise HTTPException(503, f"Obsidian write layer unavailable: {e}")
    return {"path": path, "patched": True}


@app.websocket("/ws/events")
async def ws_events(ws: WebSocket) -> None:
    if not await require_ws_token(ws):
        await ws.close(code=4401)
        return
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


from .discover import discover_modules  # noqa: E402

_loaded = discover_modules(registry, bus)
if _loaded:
    print(f"[modules] loaded: {', '.join(_loaded)}")
registry.mount_all(app)
