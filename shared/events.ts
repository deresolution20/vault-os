/**
 * VAULT shared event schema (M0.3) — single source of truth for the WS event bus.
 * Mirrored in Python: api/src/vault_api/events.py — keep the two in sync.
 * Round-trip test: api/tests/test_events_roundtrip.py validates the JSON
 * fixtures in shared/fixtures/ against BOTH sides.
 */

/** Discriminator for every event on `WS /ws/events`. */
export type VaultEventType =
  | "task_start"
  | "file_diff"
  | "log"
  | "task_done"
  | "node_update"
  | "system_vital";

interface BaseEvent {
  type: VaultEventType;
  /** Unix epoch seconds (float). */
  ts: number;
  /** Emitting module id (M7 contract), e.g. "build-agent", "indexer", "core". */
  source: string;
}

/** A build sub-agent picked up a task. */
export interface TaskStartEvent extends BaseEvent {
  type: "task_start";
  taskId: string;
  title: string;
  /** PRD difficulty tag used for routing. */
  difficulty: "trivial" | "easy" | "medium" | "hard";
  /** Which worker lane took it, e.g. "r9700", "7900xtx", "paid-api". */
  worker: string;
}

/** Streaming diff of the sub-agent's working tree (git diff — PRD §11.4). */
export interface FileDiffEvent extends BaseEvent {
  type: "file_diff";
  taskId: string;
  path: string;
  /** Unified diff chunk (may be partial; panels append). */
  diff: string;
}

/** A log line from a sub-agent or module. */
export interface LogEvent extends BaseEvent {
  type: "log";
  taskId?: string;
  level: "debug" | "info" | "warn" | "error";
  line: string;
}

/** A build sub-agent finished (or failed) a task. */
export interface TaskDoneEvent extends BaseEvent {
  type: "task_done";
  taskId: string;
  status: "success" | "failure" | "cancelled";
  /** Tokens served locally vs escalated — feeds the savings metric (M5.3). */
  tokensLocal?: number;
  tokensPaid?: number;
}

/** A vault note was created/updated/deleted → graph must refresh this node. */
export interface NodeUpdateEvent extends BaseEvent {
  type: "node_update";
  action: "created" | "updated" | "deleted";
  /** Vault-relative path, also the graph node id. */
  nodeId: string;
  title?: string;
}

/** Periodic system vitals for the HUD strip (labeled "resource", NOT activity). */
export interface SystemVitalEvent extends BaseEvent {
  type: "system_vital";
  metric: string;
  value: number;
  unit?: string;
}

export type VaultEvent =
  | TaskStartEvent
  | FileDiffEvent
  | LogEvent
  | TaskDoneEvent
  | NodeUpdateEvent
  | SystemVitalEvent;

/** Graph payload returned by GET /graph (M2.1). */
export interface GraphNode {
  id: string; // vault-relative path
  path: string; // absolute path on disk
  title: string;
  tags: string[];
  /** True when the node is a [[link]] target with no file yet. */
  unresolved?: boolean;
}

export interface GraphLink {
  source: string;
  target: string;
}

export interface VaultGraph {
  nodes: GraphNode[];
  links: GraphLink[];
}
