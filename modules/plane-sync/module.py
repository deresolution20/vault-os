"""M6.2 — Plane sync module.

Outbound: subscribes to the bus; task_start creates a Plane issue
("RUN <taskId> — <title>"), task_done moves it to a terminal state.
Inbound: POST /modules/plane-sync/webhook receives Plane webhooks and
re-emits them as bus events (log for now — the Hermes task dispatcher that
turns a card move into an executed task lands with the Hermes agent wiring).

Uses the same project/labels as tools/push_backlog_to_plane.py. No creds →
module loads but sync is disabled (logged once).
"""

import asyncio
import re
import time

import httpx
from fastapi import APIRouter, Request

from vault_api.bus import EventBus
from vault_api.config import settings
from vault_api.events import LogEvent, TaskDoneEvent, TaskStartEvent
from vault_api.modules import Module, ModuleRegistry

MODULE_ID = "plane-sync"

router = APIRouter()
_bus: EventBus | None = None
_issue_ids: dict[str, str] = {}  # taskId -> Plane issue id
_states: dict[str, str] = {}  # group -> state id, fetched lazily


def _enabled() -> bool:
    return bool(settings.plane_api_url and settings.plane_api_token)


def _api() -> str:
    return (
        f"{settings.plane_api_url.rstrip('/')}/api/v1/workspaces/"
        f"{settings.plane_workspace_slug}/projects/{settings.plane_project_id}"
    )


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={"X-API-Key": settings.plane_api_token}, timeout=10.0
    )


async def _state_id(group: str) -> str | None:
    if not _states:
        async with _client() as c:
            r = await c.get(f"{_api()}/states/")
            r.raise_for_status()
            data = r.json()
            for s in data.get("results", data if isinstance(data, list) else []):
                _states.setdefault(s["group"], s["id"])
    return _states.get(group)


# Mirror PLANNED work only (the operator 2026-07-04): ad-hoc /run commands and
# hermes chat (taskId run-xxxx) must NOT become Plane work items.
PLANNED_ID = re.compile(r"^[MX]\d")


def _should_mirror(event: TaskStartEvent) -> bool:
    return bool(PLANNED_ID.match(event.taskId)) or event.source == "build-agent"


async def _on_event(event) -> None:
    if not _enabled():
        return
    if isinstance(event, TaskStartEvent):
        if not _should_mirror(event):
            return
        async with _client() as c:
            r = await c.post(
                f"{_api()}/issues/",
                json={
                    "name": f"RUN {event.taskId} — {event.title}"[:250],
                    "description_html": (
                        f"<p>worker: {event.worker} · difficulty: "
                        f"{event.difficulty} · started by VAULT live sync</p>"
                    ),
                    "state": await _state_id("started"),
                },
            )
            r.raise_for_status()
            _issue_ids[event.taskId] = r.json()["id"]
    elif isinstance(event, TaskDoneEvent):
        issue = _issue_ids.pop(event.taskId, None)
        if issue:
            group = "completed" if event.status == "success" else "cancelled"
            async with _client() as c:
                await c.patch(
                    f"{_api()}/issues/{issue}/",
                    json={"state": await _state_id(group)},
                )


@router.post("/webhook")
async def plane_webhook(request: Request) -> dict:
    """Inbound Plane webhook → re-emit onto the bus. NOTE: Plane signs its
    webhooks; secret verification lands with the Hermes dispatcher wiring."""
    body = await request.json()
    assert _bus is not None
    await _bus.emit(
        LogEvent(
            ts=time.time(),
            source=MODULE_ID,
            level="info",
            line=f"plane webhook: {body.get('event', '?')} {body.get('action', '')}",
        )
    )
    return {"ok": True}


def register(registry: ModuleRegistry, bus: EventBus) -> None:
    global _bus
    _bus = bus
    if not _enabled():
        print("[plane-sync] no Plane creds in .env — outbound sync disabled")
    else:
        bus.subscribe(_on_event)
    registry.register(
        Module(
            id=MODULE_ID,
            name="Plane Sync",
            router=router,
            event_types=["log"],
            panel=None,
        )
    )
