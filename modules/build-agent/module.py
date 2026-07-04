"""M6.1 — Live Build module (panel-only).

Build agents (Fable, Hermes, whatever runs a task) push task_start /
file_diff / log / task_done to POST /events with source="build-agent"
(tool: tools/emit_build_events.py). This module contributes the HUD panel
that renders them; it needs no routes of its own.
"""

from vault_api.bus import EventBus
from vault_api.modules import Module, ModuleRegistry

MODULE_ID = "build-agent"


def register(registry: ModuleRegistry, bus: EventBus) -> None:
    registry.register(
        Module(
            id=MODULE_ID,
            name="Live Build",
            router=None,
            event_types=["task_start", "file_diff", "log", "task_done"],
            panel=MODULE_ID,
        )
    )
