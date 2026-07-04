/** M6.1 — Live Build panel: current task, streaming diff, tail logs. */
import type { VaultEvent } from "@vault/shared/events";
import type { PanelProps } from "../loader";

function latest<T extends VaultEvent["type"]>(
  events: VaultEvent[],
  type: T
): Extract<VaultEvent, { type: T }> | undefined {
  for (let i = events.length - 1; i >= 0; i--) {
    if (events[i].type === type)
      return events[i] as Extract<VaultEvent, { type: T }>;
  }
  return undefined;
}

export default function LiveBuildPanel({ events }: PanelProps) {
  const start = latest(events, "task_start");
  const done = latest(events, "task_done");
  const diff = latest(events, "file_diff");
  const logs = events.filter((e) => e.type === "log").slice(-6);
  const running = start && (!done || done.ts < start.ts);

  return (
    <div className="module-panel live-build">
      <div className="module-panel-title">
        LIVE BUILD {running ? "▶" : "·"}{" "}
        {start ? `${start.taskId} ${start.title}` : "idle"}
        {done && !running && ` — ${done.status}`}
      </div>
      {diff && running && (
        <pre className="live-build-diff">
          {diff.path + "\n" + diff.diff.split("\n").slice(-10).join("\n")}
        </pre>
      )}
      <div className="live-build-logs">
        {logs.map((l, i) => (
          <div key={i} className={`log-${l.type === "log" ? l.level : "info"}`}>
            {l.type === "log" ? l.line : ""}
          </div>
        ))}
      </div>
    </div>
  );
}
