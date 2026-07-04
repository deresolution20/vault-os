"""task-runner — server-side task execution for the command deck.

POST /modules/task-runner/run spawns a command in its own process group,
streams stdout/stderr lines onto the shared bus (log events), snapshots a
git diff of the working tree on exit (PRD §11.4), and emits task_done.
POST /cancel/{taskId} kills the whole process group → status "cancelled".

This is the operator's own command channel on a loopback-only, bearer-authed
API — it executes what Brice (or his TUI) tells it to, like a terminal does.
"""

from __future__ import annotations

import asyncio
import os
import signal
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from vault_api.bus import EventBus
from vault_api.config import PROJECT_ROOT
from vault_api.events import (
    FileDiffEvent,
    LogEvent,
    TaskDoneEvent,
    TaskStartEvent,
)
from vault_api.modules import Module, ModuleRegistry

MODULE_ID = "task-runner"
LOG_LINE_CAP = 500  # chars per line pushed to the bus

router = APIRouter()
_bus: EventBus | None = None
_procs: dict[str, asyncio.subprocess.Process] = {}
_cancelled: set[str] = set()


class RunRequest(BaseModel):
    cmd: list[str]
    title: str
    taskId: str | None = None
    difficulty: str = "easy"
    worker: str = "operator"
    cwd: str | None = None  # defaults to the repo root


async def _emit(event) -> None:
    assert _bus is not None
    await _bus.emit(event)


async def _git_diff(cwd: Path) -> str:
    try:
        p = await asyncio.create_subprocess_exec(
            "git", "diff", cwd=cwd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
        )
        out, _ = await asyncio.wait_for(p.communicate(), timeout=10)
        return out.decode(errors="replace")
    except (OSError, asyncio.TimeoutError):
        return ""


async def _run_task(task_id: str, req: RunRequest, cwd: Path) -> None:
    proc = _procs[task_id]
    assert proc.stdout is not None
    async for raw in proc.stdout:
        line = raw.decode(errors="replace").rstrip("\n")
        await _emit(
            LogEvent(
                ts=time.time(), source=MODULE_ID, taskId=task_id,
                level="info", line=line[:LOG_LINE_CAP],
            )
        )
    code = await proc.wait()
    _procs.pop(task_id, None)

    diff = await _git_diff(cwd)
    if diff:
        first = next(
            (l[6:] for l in diff.splitlines() if l.startswith("+++ b/")),
            "worktree",
        )
        await _emit(
            FileDiffEvent(
                ts=time.time(), source=MODULE_ID, taskId=task_id,
                path=first, diff=diff[-4000:],
            )
        )
    status = (
        "cancelled"
        if task_id in _cancelled
        else ("success" if code == 0 else "failure")
    )
    _cancelled.discard(task_id)
    await _emit(
        TaskDoneEvent(
            ts=time.time(), source=MODULE_ID, taskId=task_id, status=status
        )
    )


@router.post("/run", status_code=202)
async def run(req: RunRequest) -> dict:
    task_id = req.taskId or f"run-{uuid.uuid4().hex[:8]}"
    if task_id in _procs:
        raise HTTPException(409, f"task {task_id} already running")
    cwd = Path(req.cwd) if req.cwd else PROJECT_ROOT
    if not cwd.is_dir():
        raise HTTPException(400, f"cwd not a directory: {cwd}")
    try:
        proc = await asyncio.create_subprocess_exec(
            *req.cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            # own process group so cancel kills the whole tree
            preexec_fn=os.setsid,
        )
    except (OSError, ValueError) as e:
        raise HTTPException(400, f"spawn failed: {e}")
    _procs[task_id] = proc
    await _emit(
        TaskStartEvent(
            ts=time.time(), source=MODULE_ID, taskId=task_id,
            title=req.title, difficulty=req.difficulty, worker=req.worker,  # type: ignore[arg-type]
        )
    )
    asyncio.create_task(_run_task(task_id, req, cwd))
    return {"taskId": task_id, "pid": proc.pid}


@router.post("/cancel/{task_id}")
async def cancel(task_id: str) -> dict:
    proc = _procs.get(task_id)
    if proc is None:
        raise HTTPException(404, f"no running task {task_id}")
    _cancelled.add(task_id)
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except ProcessLookupError:
        pass
    return {"taskId": task_id, "cancelled": True}


@router.get("/running")
async def running() -> dict:
    return {"tasks": list(_procs.keys())}


def register(registry: ModuleRegistry, bus: EventBus) -> None:
    global _bus
    _bus = bus
    registry.register(
        Module(
            id=MODULE_ID,
            name="Task Runner",
            router=router,
            event_types=["task_start", "log", "file_diff", "task_done"],
            panel=None,
        )
    )
