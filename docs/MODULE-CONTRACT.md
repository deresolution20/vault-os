# VAULT Module Contract (M7.1 sketch — day-one, per PRD §3.8)

**Status:** contract sketched during M0 (as required by PRD §9). Full
enforcement + refactor of built-ins lands in M7.2; the drop-in proof is
M7.3 (`hello-module`).

Every capability in VAULT — RAG, vault write layer, model serving, build
telemetry, and future video/ComfyUI — is a **Module**. Core knows nothing
about any specific capability; it discovers modules, mounts them, and
brokers their events. Removing a module never breaks the others.

## What a module registers

| Part | Backend (Python) | Front-end (React) |
|---|---|---|
| **(a) REST routes** | `fastapi.APIRouter`, mounted by core at `/modules/<id>/…` | consumed via fetch |
| **(b) WS event types** | declared list of `VaultEvent.type` values it emits on the shared bus | panels subscribe by type |
| **(c) Panel (optional)** | panel component **id** in the manifest | `desktop/src/modules/<id>/Panel.tsx`, lazy-loaded from the manifest |

## Backend interface (implemented: `api/src/vault_api/modules.py`)

```python
Module(
    id="hello-module",            # kebab-case; doubles as event `source`
    name="Hello Module",
    router=router,                 # (a) APIRouter | None
    event_types=["log"],           # (b) VaultEvent types it may emit
    panel="hello-module",          # (c) panel id | None
    on_startup=start,              # optional lifecycle hooks
    on_shutdown=stop,
)
registry.register(module)
```

- Core mounts every router under `/modules/<id>` (`ModuleRegistry.mount_all`).
- Modules emit events **only** through the shared bus (`vault_api.bus.bus.emit`),
  stamped with `source=<module id>`. New event types extend the schema in
  `shared/events.ts` + `api/src/vault_api/events.py` (both sides, same PR).
- `GET /modules` returns the manifest; the front-end mounts panels from it.

## Front-end panel convention

- One folder per module: `desktop/src/modules/<id>/Panel.tsx`
  (default export = React component).
- Panels receive the WS event stream filtered to the module's declared
  `eventTypes` plus a slot in the HUD grid. Panels never own a second
  WebSocket connection.
- Panels must not touch the Three.js canvas directly; graph interactions go
  through core-provided hooks (keeps the M3 canvas single-owner).

## Rules

1. **No cross-module imports.** Modules talk via REST or the event bus.
2. **Schema changes are two-sided** (TS + Pydantic) and covered by the
   round-trip fixture test.
3. **Local-only by default**: modules bind to localhost through core; a
   module never opens its own external port.
4. Module workers that need GPU inference call the M5 router — never a
   card directly — so future modules inherit local-first/paid-fallback.

## Why this satisfies the "video/ComfyUI later" requirement

A future ComfyUI module is: an `APIRouter` proxying a ComfyUI worker, a set
of `task_*`/`log` events it emits while generating, and a panel rendering
previews. It plugs into the same registry, bus, and model router — zero core
changes. That path is proven in Step One by M7.3's `hello-module`.
