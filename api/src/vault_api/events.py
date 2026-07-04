"""VAULT shared event schema (M0.3) — Pydantic mirror of shared/events.ts.

Keep in sync with the TypeScript side. The round-trip test
(tests/test_events_roundtrip.py) validates shared/fixtures/*.json against
these models; the TS side type-checks the same fixtures.
"""

from __future__ import annotations

from typing import Literal, Union

from pydantic import BaseModel, Field


class BaseEvent(BaseModel):
    ts: float = Field(description="Unix epoch seconds")
    source: str = Field(description="Emitting module id (M7 contract)")


class TaskStartEvent(BaseEvent):
    type: Literal["task_start"] = "task_start"
    taskId: str
    title: str
    difficulty: Literal["trivial", "easy", "medium", "hard"]
    worker: str


class FileDiffEvent(BaseEvent):
    type: Literal["file_diff"] = "file_diff"
    taskId: str
    path: str
    diff: str


class LogEvent(BaseEvent):
    type: Literal["log"] = "log"
    taskId: str | None = None
    level: Literal["debug", "info", "warn", "error"]
    line: str


class TaskDoneEvent(BaseEvent):
    type: Literal["task_done"] = "task_done"
    taskId: str
    status: Literal["success", "failure", "cancelled"]
    tokensLocal: int | None = None
    tokensPaid: int | None = None


class NodeUpdateEvent(BaseEvent):
    type: Literal["node_update"] = "node_update"
    action: Literal["created", "updated", "deleted"]
    nodeId: str
    title: str | None = None


class SystemVitalEvent(BaseEvent):
    type: Literal["system_vital"] = "system_vital"
    metric: str
    value: float
    unit: str | None = None


VaultEvent = Union[
    TaskStartEvent,
    FileDiffEvent,
    LogEvent,
    TaskDoneEvent,
    NodeUpdateEvent,
    SystemVitalEvent,
]


class GraphNode(BaseModel):
    id: str
    path: str
    title: str
    tags: list[str] = []
    unresolved: bool | None = None


class GraphLink(BaseModel):
    source: str
    target: str


class VaultGraph(BaseModel):
    nodes: list[GraphNode]
    links: list[GraphLink]
