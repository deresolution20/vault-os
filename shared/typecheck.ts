/**
 * M0.3 AC (TS side): the fixtures conform to VaultEvent at compile time.
 * Run: pnpm --dir shared exec tsc --noEmit --resolveJsonModule typecheck.ts
 */
import fixtures from "./fixtures/events.json";
import type { VaultEvent } from "./events";

// Compile-time conformance: the literal JSON must satisfy the union.
const events: VaultEvent[] = fixtures as VaultEvent[];

// One statically-typed instance of each variant.
const samples: VaultEvent[] = [
  { type: "task_start", ts: 0, source: "s", taskId: "t", title: "x", difficulty: "hard", worker: "r9700" },
  { type: "file_diff", ts: 0, source: "s", taskId: "t", path: "p", diff: "d" },
  { type: "log", ts: 0, source: "s", level: "info", line: "l" },
  { type: "task_done", ts: 0, source: "s", taskId: "t", status: "success" },
  { type: "node_update", ts: 0, source: "s", action: "updated", nodeId: "n" },
  { type: "system_vital", ts: 0, source: "s", metric: "m", value: 1 },
];

export { events, samples };
