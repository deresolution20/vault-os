"""Module contract + registry (M7.1) — every VAULT capability is a Module.

A Module registers:
  (a) REST routes        — an APIRouter mounted under /modules/<id>
  (b) WS event types     — the VaultEvent `type` values it may emit
  (c) optional panel     — the id of a front-end panel component
                           (desktop/src/modules/<id>/Panel.tsx, lazy-loaded)

Core discovers modules at startup and mounts them; removing a module must
never break the others (M7.2 AC). Future video/ComfyUI capabilities arrive
as new Modules — no core changes (M7.3 proves this with hello-module).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Awaitable, Callable

from fastapi import APIRouter, FastAPI


@dataclass
class Module:
    id: str  # kebab-case, unique; also the event `source`
    name: str
    router: APIRouter | None = None  # (a) REST routes
    event_types: list[str] = field(default_factory=list)  # (b) WS events emitted
    panel: str | None = None  # (c) front-end panel component id
    # optional lifecycle hooks (indexer watch loops, worker health checks, ...)
    on_startup: Callable[[], Awaitable[None]] | None = None
    on_shutdown: Callable[[], Awaitable[None]] | None = None


class ModuleRegistry:
    def __init__(self) -> None:
        self._modules: dict[str, Module] = {}

    def register(self, module: Module) -> None:
        if module.id in self._modules:
            raise ValueError(f"duplicate module id: {module.id}")
        self._modules[module.id] = module

    def mount_all(self, app: FastAPI) -> None:
        for mod in self._modules.values():
            if mod.router is not None:
                app.include_router(
                    mod.router, prefix=f"/modules/{mod.id}", tags=[mod.id]
                )

    def manifest(self) -> list[dict]:
        """GET /modules — the front-end uses this to mount panels dynamically."""
        return [
            {
                "id": m.id,
                "name": m.name,
                "eventTypes": m.event_types,
                "panel": m.panel,
            }
            for m in self._modules.values()
        ]

    @property
    def modules(self) -> list[Module]:
        return list(self._modules.values())


registry = ModuleRegistry()
