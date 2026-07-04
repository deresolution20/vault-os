"""M6.3 — Grafana embed module (panel-only).

Surfaces GPU VRAM/temp/util panels from Grafana Cloud via signed embed /
iframe URL. Labeled RESOURCE, never activity (PRD §3.2 — the gfx1201 HIP
idle bug makes util meaningless as a work signal).
"""

from vault_api.bus import EventBus
from vault_api.config import settings
from vault_api.modules import Module, ModuleRegistry

MODULE_ID = "grafana"


def register(registry: ModuleRegistry, bus: EventBus) -> None:
    registry.register(
        Module(
            id=MODULE_ID,
            name="System Vitals (Grafana)",
            router=None,
            event_types=[],
            panel=MODULE_ID,
            config={"embedUrl": settings.grafana_embed_url},
        )
    )
