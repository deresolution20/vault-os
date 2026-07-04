"""gpu-deck — mission-control module: what every GPU is doing RIGHT NOW.

Mimics Claude Code /workflows: per-GPU tree of residents (VAULT workers,
ollama models), running tasks with their Plane chain (project → milestone →
issue), and recent history. Activity comes from events + API state ONLY —
never GPU util/heat (PRD §3.2).

Surfaces: HUD panel + dedicated window + tools/vault-top (terminal TUI),
all fed by GET /modules/gpu-deck/state.
"""

from __future__ import annotations

import asyncio
import glob
import subprocess
import time
from dataclasses import dataclass, field

import httpx
from fastapi import APIRouter, HTTPException

from vault_api.bus import EventBus
from vault_api.config import settings
from vault_api.events import TaskDoneEvent, TaskStartEvent
from vault_api.modules import Module, ModuleRegistry

MODULE_ID = "gpu-deck"
HISTORY_LIMIT = 10
PLANE_CACHE_TTL = 60.0

router = APIRouter()

# ── task tracking (bus-fed) ──────────────────────────────────────────────

_running: dict[str, dict] = {}  # taskId -> info
_history: list[dict] = []  # most recent first
# drill-down transcripts: every event a task emitted, capped per task;
# pruned alongside history so memory stays bounded
_task_events: dict[str, list[dict]] = {}
TASK_EVENT_CAP = 500

# history + transcripts survive API restarts (regenerable → .tmp)
from vault_api.config import PROJECT_ROOT  # noqa: E402

PERSIST_PATH = PROJECT_ROOT / ".tmp/gpu-deck-history.json"


def _save() -> None:
    try:
        PERSIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        import json

        PERSIST_PATH.write_text(
            json.dumps({"history": _history, "taskEvents": _task_events})
        )
    except OSError as e:
        print(f"[gpu-deck] persist failed: {e}")


def _load() -> None:
    try:
        import json

        data = json.loads(PERSIST_PATH.read_text())
        _history.extend(data.get("history", [])[:HISTORY_LIMIT])
        _task_events.update(data.get("taskEvents", {}))
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as e:
        print(f"[gpu-deck] history load failed: {e}")


def _record(task_id: str, event) -> None:
    log = _task_events.setdefault(task_id, [])
    log.append(event.model_dump(exclude_none=True))
    del log[:-TASK_EVENT_CAP]


async def _on_event(event) -> None:
    task_id = getattr(event, "taskId", None)
    if task_id:
        _record(task_id, event)
    if isinstance(event, TaskStartEvent):
        _running[event.taskId] = {
            "taskId": event.taskId,
            "title": event.title,
            "difficulty": event.difficulty,
            "worker": event.worker,
            "startedAt": event.ts,
        }
    elif isinstance(event, TaskDoneEvent):
        info = _running.pop(event.taskId, None) or {"taskId": event.taskId}
        info.update(
            status=event.status,
            finishedAt=event.ts,
            durationS=round(event.ts - info.get("startedAt", event.ts), 1),
            tokensLocal=event.tokensLocal,
            tokensPaid=event.tokensPaid,
        )
        _history.insert(0, info)
        del _history[HISTORY_LIMIT:]
        # prune transcripts of tasks that fell off the history window
        keep = set(_running) | {h["taskId"] for h in _history}
        for tid in list(_task_events):
            if tid not in keep:
                del _task_events[tid]
        _save()


# ── GPU hardware truth (sysfs + nvidia-smi) ─────────────────────────────


def _amd_gpus() -> list[dict]:
    gpus = []
    for vendor_path in glob.glob("/sys/class/drm/card*/device/vendor"):
        try:
            if open(vendor_path).read().strip() != "0x1002":
                continue
            dev = vendor_path.rsplit("/", 1)[0]
            total = int(open(f"{dev}/mem_info_vram_total").read())
            used = int(open(f"{dev}/mem_info_vram_used").read())
            # gfx1201 R9700 is 0x7551; extend map as cards arrive
            device_id = open(f"{dev}/device").read().strip()
            name = {
                "0x7551": "AMD R9700 (gfx1201)",
                "0x744c": "AMD 7900 XTX (gfx1100)",
            }.get(device_id, f"AMD GPU {device_id}")
            gpus.append(
                {
                    "id": name.split()[1].lower(),
                    "name": name,
                    "vramUsedGB": round(used / 1e9, 1),
                    "vramTotalGB": round(total / 1e9, 1),
                }
            )
        except OSError:
            continue
    return gpus


def _nvidia_gpus() -> list[dict]:
    try:
        out = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return []
    gpus = []
    for line in out.splitlines():
        name, used, total = [x.strip() for x in line.split(",")]
        gpus.append(
            {
                "id": "4060ti" if "4060" in name else name.lower().replace(" ", "-"),
                "name": name,
                "vramUsedGB": round(int(used) / 1024, 1),
                "vramTotalGB": round(int(total) / 1024, 1),
            }
        )
    return gpus


# ── residents: VAULT workers + ollama ────────────────────────────────────

WORKERS = [
    {"id": "r9700-worker", "gpu": "r9700", "url": settings.worker_r9700_url,
     "unit": "vault-worker-r9700"},
    {"id": "7900xtx-worker", "gpu": "7900xtx", "url": settings.worker_7900xtx_url,
     "unit": "vault-worker-7900xtx"},
]


async def _worker_state(w: dict) -> dict:
    state = {"id": w["id"], "gpu": w["gpu"], "unit": w["unit"], "up": False}
    base = w["url"].rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=2.0) as c:
            r = await c.get(f"{base}/models")
            if r.status_code == 200:
                d = r.json()
                models = d.get("data", d.get("models", []))
                state["up"] = True
                state["model"] = (
                    (models[0].get("id") or models[0].get("name")) if models else "?"
                )
            # /slots lives at server root, not under /v1
            root = base.rsplit("/v1", 1)[0]
            r = await c.get(f"{root}/slots")
            if r.status_code == 200:
                slots = r.json()
                busy = [s for s in slots if s.get("is_processing")]
                state["activeSlots"] = len(busy)
                if busy:
                    state["currentPrompt"] = str(
                        busy[0].get("prompt", "")
                    )[:120]
    except httpx.HTTPError:
        pass
    return state


async def _ollama_state() -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=2.0) as c:
            r = await c.get(f"{settings.ollama_url}/api/ps")
            r.raise_for_status()
            models = r.json().get("models", [])
    except httpx.HTTPError:
        return []
    return [
        {
            "model": m.get("name"),
            "vramGB": round(m.get("size_vram", 0) / 1e9, 1),
            "totalGB": round(m.get("size", 0) / 1e9, 1),
            "until": m.get("expires_at", ""),
            # ollama does not expose per-card placement; spans cards when big
            "placement": "ollama-managed (placement not exposed)",
        }
        for m in models
    ]


# ── Plane chain resolution (cached) ──────────────────────────────────────

_plane_cache: dict[str, tuple[float, dict]] = {}


async def _plane_chain(task_id: str) -> dict:
    """taskId (e.g. 'M6.1' or 'M6.1-demo') → project/milestone/issue chain."""
    if not (settings.plane_api_url and settings.plane_api_token):
        return {"linked": False, "reason": "plane not configured"}
    now = time.monotonic()
    if task_id in _plane_cache and now - _plane_cache[task_id][0] < PLANE_CACHE_TTL:
        return _plane_cache[task_id][1]

    api = (
        f"{settings.plane_api_url.rstrip('/')}/api/v1/workspaces/"
        f"{settings.plane_workspace_slug}/projects/{settings.plane_project_id}"
    )
    chain: dict = {"linked": False, "reason": "unplanned"}
    try:
        async with httpx.AsyncClient(
            headers={"X-API-Key": settings.plane_api_token}, timeout=5.0
        ) as c:
            pr = await c.get(f"{api}/")
            pdata = pr.json() if pr.status_code == 200 else {}
            project_name = pdata.get("name", "?")
            project_ident = pdata.get("identifier", "")
            r = await c.get(f"{api}/issues/", params={"per_page": 100})
            r.raise_for_status()
            data = r.json()
            issues = data.get("results", data if isinstance(data, list) else [])
            prefix = task_id.split("-")[0]  # M6.1-demo -> M6.1
            match = next(
                (i for i in issues if i["name"].startswith((task_id, f"RUN {task_id}", prefix))),
                None,
            )
            if match:
                milestone = match.get("cycle") or f"module:{prefix.split('.')[0]}"
                web = (settings.plane_web_url or settings.plane_api_url).rstrip("/")
                # current Plane web routes issues as /browse/<IDENT>-<seq>/
                seq = match.get("sequence_id")
                url = (
                    f"{web}/{settings.plane_workspace_slug}/browse/"
                    f"{project_ident}-{seq}/"
                    if project_ident and seq
                    else f"{web}/{settings.plane_workspace_slug}/projects/"
                    f"{settings.plane_project_id}/issues/{match['id']}"
                )
                chain = {
                    "linked": True,
                    "project": project_name,
                    "milestone": milestone,
                    "issue": match["name"],
                    "state": match.get("state"),
                    "url": url,
                }
    except httpx.HTTPError as e:
        chain = {"linked": False, "reason": f"plane error: {e}"}
    _plane_cache[task_id] = (now, chain)
    return chain


# ── routes ───────────────────────────────────────────────────────────────


@router.get("/state")
async def deck_state() -> dict:
    from vault_api.router import model_router

    workers, ollama = await asyncio.gather(
        asyncio.gather(*[_worker_state(w) for w in WORKERS]),
        _ollama_state(),
    )
    running = []
    for info in _running.values():
        running.append({**info, "plane": await _plane_chain(info["taskId"])})
    return {
        "ts": time.time(),
        "gpus": _amd_gpus() + _nvidia_gpus(),
        "workers": list(workers),
        "ollama": ollama,
        "runningTasks": running,
        "history": _history,
        "ledger": model_router.ledger.as_dict(),
    }


@router.get("/task/{task_id}")
async def task_detail(task_id: str) -> dict:
    """Drill-down: a task's info, Plane chain, and full event transcript."""
    info = _running.get(task_id) or next(
        (h for h in _history if h["taskId"] == task_id), None
    )
    if info is None and task_id not in _task_events:
        raise HTTPException(404, f"unknown task: {task_id}")
    return {
        "info": info or {"taskId": task_id},
        "running": task_id in _running,
        "plane": await _plane_chain(task_id),
        "events": _task_events.get(task_id, []),
    }


@router.post("/workers/{unit}/{action}")
async def worker_control(unit: str, action: str) -> dict:
    """Light controls: start/stop the VAULT worker user-units only."""
    allowed_units = {w["unit"] for w in WORKERS}
    if unit not in allowed_units or action not in ("start", "stop"):
        raise HTTPException(400, "unknown unit or action")
    p = subprocess.run(
        ["systemctl", "--user", action, unit], capture_output=True, text=True
    )
    if p.returncode != 0:
        raise HTTPException(500, p.stderr.strip()[:200])
    return {"unit": unit, "action": action, "ok": True}


def register(registry: ModuleRegistry, bus: EventBus) -> None:
    _load()
    bus.subscribe(_on_event)
    registry.register(
        Module(
            id=MODULE_ID,
            name="GPU Deck",
            router=router,
            event_types=[],
            panel=None,  # deck is docked into the core HUD; window via open_deck
        )
    )
