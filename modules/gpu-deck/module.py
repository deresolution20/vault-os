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
from pathlib import Path
from dataclasses import dataclass, field

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

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

# ── throughput: (ts, cumulative_tokens) samples per lane, ~1h window ─────
SAMPLE_EVERY_S = 5.0
WINDOW_S = 3600.0
# lanes: worker ids ("r9700", "7900xtx") + "paid-api"
_samples: dict[str, list[list[float]]] = {}
_sampler_task = None

CLOUD_STATS = PROJECT_ROOT / ".tmp/cloud-proxy-stats.jsonl"
CLOUD_LIVE = PROJECT_ROOT / ".tmp/cloud-proxy-live.json"

METRIC_TOKENS = "llamacpp:tokens_predicted_total"


def _push_sample(lane: str, ts: float, total: float) -> None:
    buf = _samples.setdefault(lane, [])
    buf.append([ts, total])
    cutoff = ts - WINDOW_S
    while buf and buf[0][0] < cutoff:
        buf.pop(0)


def _throughput() -> dict:
    """Per-lane liveTps + hourTokens + hourAvgTps (rate while generating)."""
    out = {}
    for lane, buf in _samples.items():
        if len(buf) < 2:
            out[lane] = {"liveTps": 0.0, "hourTokens": 0, "hourAvgTps": 0.0}
            continue
        (t0, c0), (t1, c1) = buf[-2], buf[-1]
        live = max(0.0, (c1 - c0) / max(t1 - t0, 1e-6))
        hour_tokens = max(0, int(buf[-1][1] - buf[0][1]))
        active_rates = []
        for (ta, ca), (tb, cb) in zip(buf, buf[1:]):
            d = cb - ca
            if d > 0:
                active_rates.append(d / max(tb - ta, 1e-6))
        avg = sum(active_rates) / len(active_rates) if active_rates else 0.0
        out[lane] = {
            "liveTps": round(live, 1),
            "hourTokens": hour_tokens,
            "hourAvgTps": round(avg, 1),
        }
    return out


async def _sample_once() -> None:
    now = time.time()
    # worker lanes: prometheus counter (counter resets on worker restart —
    # guard with max(prev, new)? no: a reset makes delta negative, which the
    # rate math clamps to 0 and the window total ignores via max(0, ...))
    for w in WORKERS:
        root = w["url"].rstrip("/").rsplit("/v1", 1)[0]
        try:
            async with httpx.AsyncClient(timeout=2.0) as c:
                r = await c.get(f"{root}/metrics")
                if r.status_code != 200:
                    continue
                completed = 0.0
                for line in r.text.splitlines():
                    if line.startswith(METRIC_TOKENS):
                        completed = float(line.split()[-1])
                        break
                # the counter only moves on request COMPLETION; add tokens
                # decoded so far by in-flight slots for a true live rate
                in_flight = 0.0
                rs = await c.get(f"{root}/slots")
                if rs.status_code == 200:
                    for slot in rs.json():
                        if slot.get("is_processing"):
                            nxt = slot.get("next_token") or [{}]
                            in_flight += float(nxt[0].get("n_decoded", 0))
            _push_sample(w["gpu"], now, completed + in_flight)
        except (httpx.HTTPError, ValueError):
            continue
    # paid lane from the router ledger (cumulative counter, same math)
    from vault_api.router import model_router

    _push_sample("paid-api", now, float(model_router.ledger.paid_tokens))


async def _sampler_loop() -> None:
    while True:
        try:
            await _sample_once()
        except Exception as e:
            print(f"[gpu-deck] sampler: {e}")
        await asyncio.sleep(SAMPLE_EVERY_S)


async def _start_sampler() -> None:
    global _sampler_task
    _sampler_task = asyncio.create_task(_sampler_loop())


async def _stop_sampler() -> None:
    if _sampler_task:
        _sampler_task.cancel()
    _save()  # keep rate windows across restarts


def _cloud_state() -> list[dict]:
    """Per-model cloud-orchestrator stats from the relay's files, last hour."""
    import json

    cutoff = time.time() - WINDOW_S
    per_model: dict[str, dict] = {}
    try:
        for line in CLOUD_STATS.read_text().splitlines()[-5000:]:
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("ts", 0) < cutoff:
                continue
            m = per_model.setdefault(
                rec.get("model") or "?",
                {
                    "model": rec.get("model") or "?",
                    "requests": 0,
                    "tokensIn": 0,
                    "tokensOut": 0,
                    "latencies": [],
                    "tps": [],
                    "approx": False,
                    "inFlight": 0,
                },
            )
            m["requests"] += 1
            m["tokensIn"] += rec.get("tokensIn", 0) or 0
            m["tokensOut"] += rec.get("tokensOut", 0) or 0
            m["latencies"].append(rec.get("durationMs", 0))
            if rec.get("tokensOut") and rec.get("durationMs"):
                m["tps"].append(rec["tokensOut"] / (rec["durationMs"] / 1000))
            if rec.get("approx"):
                m["approx"] = True
    except FileNotFoundError:
        pass
    try:
        live = json.loads(CLOUD_LIVE.read_text())
        for model in live.get("inFlightModels", []):  # legacy + current key
            m = per_model.setdefault(
                model,
                {
                    "model": model,
                    "requests": 0,
                    "tokensIn": 0,
                    "tokensOut": 0,
                    "latencies": [],
                    "tps": [],
                    "approx": False,
                    "inFlight": 0,
                },
            )
            m["inFlight"] += 1
    except (FileNotFoundError, ValueError):
        pass
    out = []
    for m in per_model.values():
        lat = m.pop("latencies")
        tps = m.pop("tps")
        m["avgLatencyMs"] = int(sum(lat) / len(lat)) if lat else 0
        m["avgTps"] = round(sum(tps) / len(tps), 1) if tps else 0.0
        out.append(m)
    return sorted(out, key=lambda m: -m["requests"])


def _save() -> None:
    try:
        PERSIST_PATH.parent.mkdir(parents=True, exist_ok=True)
        import json

        PERSIST_PATH.write_text(
            json.dumps(
                {
                    "history": _history,
                    "taskEvents": _task_events,
                    "samples": _samples,
                }
            )
        )
    except OSError as e:
        print(f"[gpu-deck] persist failed: {e}")


def _load() -> None:
    try:
        import json

        data = json.loads(PERSIST_PATH.read_text())
        _history.extend(data.get("history", [])[:HISTORY_LIMIT])
        _task_events.update(data.get("taskEvents", {}))
        _samples.update(data.get("samples", {}))
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
     "unit": "vault-worker-r9700", "defaultModel": "qwen3-32b"},
    {"id": "7900xtx-worker", "gpu": "7900xtx", "url": settings.worker_7900xtx_url,
     "unit": "vault-worker-7900xtx", "defaultModel": "(pick with /model)"},
]


def _selected_model(gpu: str, default: str) -> str:
    """The model this worker will load on next start (sticky selection)."""
    import json

    try:
        sel = json.loads(
            (PROJECT_ROOT / f".tmp/worker-{gpu}.model").read_text()
        )
        return sel.get("alias") or default
    except (FileNotFoundError, ValueError):
        return default


async def _worker_state(w: dict) -> dict:
    state = {
        "id": w["id"],
        "gpu": w["gpu"],
        "unit": w["unit"],
        "up": False,
        "selectedModel": _selected_model(w["gpu"], w["defaultModel"]),
    }
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
        "throughput": _throughput(),
        "cloud": _cloud_state(),
    }


@router.get("/cloud-live")
async def cloud_live() -> dict:
    """Cheap, poll-friendly: is the cloud orchestrator thinking RIGHT NOW."""
    import json

    try:
        live = json.loads(CLOUD_LIVE.read_text())
    except (FileNotFoundError, ValueError):
        live = {}
    now = time.time()
    in_flight = [
        {
            "model": e.get("model"),
            "elapsedS": round(now - e.get("startedTs", now), 1),
        }
        for e in live.get("inFlight", [])
    ]
    return {"inFlight": in_flight}


@router.post("/cloud-reset")
async def cloud_reset() -> dict:
    """Zero the cloud-orchestrator window (testing). The current stats file
    is archived to *.jsonl.1 rather than destroyed."""
    cleared = 0
    try:
        lines = CLOUD_STATS.read_text().splitlines()
        cleared = len(lines)
        CLOUD_STATS.with_suffix(".jsonl.1").write_text("\n".join(lines) + "\n")
        CLOUD_STATS.write_text("")
    except FileNotFoundError:
        pass
    return {"cleared": cleared, "archivedTo": str(CLOUD_STATS) + ".1"}


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


# ── model catalog + switcher ─────────────────────────────────────────────

OLLAMA_STORES = [Path("/var/lib/ollama-r9700/models")]
# archs the bundled llama.cpp (b9870) cannot load (ollama-fork additions)
UNSUPPORTED_ARCHS = {"qwen35", "qwen35moe"}


def _gguf_arch(path: Path) -> str:
    """Read general.architecture from a GGUF header (first KV is usually it)."""
    import struct

    try:
        with path.open("rb") as f:
            head = f.read(65536)
        if head[:4] != b"GGUF":
            return "?"
        # search the header window for the arch key and read the string after
        idx = head.find(b"general.architecture")
        if idx < 0:
            return "?"
        off = idx + len(b"general.architecture")
        vtype = struct.unpack_from("<I", head, off)[0]
        if vtype != 8:  # GGUF string
            return "?"
        slen = struct.unpack_from("<Q", head, off + 4)[0]
        return head[off + 12 : off + 12 + min(slen, 32)].decode(errors="replace")
    except (OSError, struct.error):
        return "?"


def _model_catalog() -> list[dict]:
    import json

    out = []
    for store in OLLAMA_STORES:
        manifests = store / "manifests/registry.ollama.ai"
        if not manifests.is_dir():
            continue
        for mf in manifests.rglob("*"):
            if not mf.is_file():
                continue
            try:
                data = json.loads(mf.read_text())
                layer = next(
                    (
                        l
                        for l in (data.get("layers") or [])
                        if "model" in (l.get("mediaType") or "")
                    ),
                    None,
                )
                if not layer:
                    continue
                blob = store / "blobs" / layer["digest"].replace(":", "-")
                if not blob.is_file():
                    continue  # cloud model or partial
                rel = mf.relative_to(manifests).parts
                name = (
                    f"{rel[-2]}:{rel[-1]}"
                    if rel[0] == "library"
                    else f"{'/'.join(rel[:-1])}:{rel[-1]}"
                )
                arch = _gguf_arch(blob)
                out.append(
                    {
                        "name": name,
                        "path": str(blob),
                        "sizeGB": round(layer["size"] / 1e9, 1),
                        "arch": arch,
                        "loadable": arch not in UNSUPPORTED_ARCHS,
                    }
                )
            except (ValueError, OSError):
                continue
    return sorted(out, key=lambda m: m["name"])


@router.get("/models")
async def models() -> dict:
    return {"models": _model_catalog()}


class ModelSelect(BaseModel):
    path: str
    alias: str


@router.post("/workers/{unit}/model")
async def set_worker_model(unit: str, sel: ModelSelect) -> dict:
    """Switch a worker's model: persist the selection, restart the unit."""
    import json

    worker = next((w for w in WORKERS if w["unit"] == unit), None)
    if worker is None:
        raise HTTPException(400, f"unknown unit {unit}")
    p = Path(sel.path)
    if not (p.is_file() and p.open("rb").read(4) == b"GGUF"):
        raise HTTPException(400, f"not a readable GGUF: {sel.path}")
    sel_file = PROJECT_ROOT / f".tmp/worker-{worker['gpu']}.model"
    sel_file.parent.mkdir(parents=True, exist_ok=True)
    sel_file.write_text(json.dumps({"path": sel.path, "alias": sel.alias}))
    # restart (or start) the worker with the new selection; a missing unit
    # (card not installed yet) still keeps the sticky selection
    subprocess.run(["systemctl", "--user", "stop", unit], capture_output=True)
    p2 = subprocess.run(
        ["systemctl", "--user", "start", unit], capture_output=True, text=True
    )
    if p2.returncode != 0:
        return {
            "unit": unit,
            "model": sel.alias,
            "restarted": False,
            "note": f"selection saved; start failed: {p2.stderr.strip()[:150]}",
        }
    return {"unit": unit, "model": sel.alias, "restarted": True}


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
            on_startup=_start_sampler,
            on_shutdown=_stop_sampler,
        )
    )
