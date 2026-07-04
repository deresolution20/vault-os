"""M7.3 — hello-module: the drop-in modularity proof.

One route, one event, one panel — zero core changes. This folder is the
template for future ComfyUI/video modules (PRD §10).
"""

import time

from fastapi import APIRouter

from vault_api.bus import EventBus
from vault_api.events import LogEvent
from vault_api.modules import Module, ModuleRegistry

MODULE_ID = "hello-module"

router = APIRouter()
_bus: EventBus | None = None


@router.get("/hello")
async def hello() -> dict:
    return {"module": MODULE_ID, "message": "hello from a drop-in module"}


@router.post("/wave")
async def wave() -> dict:
    """Emit one event onto the shared bus — shows up in the module's panel."""
    assert _bus is not None
    await _bus.emit(
        LogEvent(
            ts=time.time(),
            source=MODULE_ID,
            level="info",
            line="👋 wave from hello-module",
        )
    )
    return {"waved": True}


def register(registry: ModuleRegistry, bus: EventBus) -> None:
    global _bus
    _bus = bus
    registry.register(
        Module(
            id=MODULE_ID,
            name="Hello Module",
            router=router,
            event_types=["log"],
            panel=MODULE_ID,
        )
    )
