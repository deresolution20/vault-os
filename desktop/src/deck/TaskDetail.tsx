/** Drill-down view: one task's info, Plane chain, and live event transcript. */
import { useEffect, useRef, useState } from "react";
import { openUrl } from "@tauri-apps/plugin-opener";
import { getConfig } from "../api";

interface Detail {
  info: {
    taskId: string;
    title?: string;
    difficulty?: string;
    worker?: string;
    status?: string;
    durationS?: number;
  };
  running: boolean;
  plane: {
    linked: boolean;
    project?: string;
    milestone?: string;
    issue?: string;
    state?: string;
    url?: string;
    reason?: string;
  };
  events: {
    type: string;
    ts: number;
    level?: string;
    line?: string;
    path?: string;
    diff?: string;
    status?: string;
  }[];
}

export default function TaskDetail({
  taskId,
  onBack,
}: {
  taskId: string;
  onBack: () => void;
}) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [err, setErr] = useState("");
  const logEnd = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let stop = false;
    const poll = async () => {
      if (stop) return;
      try {
        const cfg = await getConfig();
        const r = await fetch(
          `${cfg.apiUrl}/modules/gpu-deck/task/${encodeURIComponent(taskId)}`,
          { headers: { Authorization: `Bearer ${cfg.token}` } }
        );
        if (!r.ok) throw new Error(`task: ${r.status}`);
        setDetail(await r.json());
        setErr("");
      } catch (e) {
        setErr(String(e));
      }
      setTimeout(poll, 2000);
    };
    poll();
    return () => {
      stop = true;
    };
  }, [taskId]);

  useEffect(() => {
    if (detail?.running)
      logEnd.current?.scrollIntoView({ behavior: "smooth" });
  }, [detail]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onBack();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onBack]);

  if (!detail)
    return (
      <div className="deck-detail">
        <div className="deck-err">{err || "loading…"}</div>
      </div>
    );

  const { info, plane, events } = detail;
  const lastDiff = [...events].reverse().find((e) => e.type === "file_diff");

  return (
    <div className="deck-detail">
      <div className="deck-title">
        <button className="deck-btn" onClick={onBack}>
          ‹ back
        </button>{" "}
        {detail.running ? "▶" : info.status === "success" ? "✓" : "·"}{" "}
        {info.taskId} {info.title ?? ""}
        <span className="deck-dim">
          {" "}
          [{info.difficulty ?? "?"} · {info.worker ?? "?"}
          {info.durationS != null && ` · ${info.durationS}s`}]
        </span>
      </div>

      <div className="deck-plane" style={{ paddingLeft: 0 }}>
        {plane.linked ? (
          <>
            {plane.project} › {String(plane.milestone)} › {plane.issue}{" "}
            {plane.url && (
              <button
                className="deck-btn"
                onClick={() => openUrl(plane.url!).catch(console.error)}
              >
                open in Plane ↗
              </button>
            )}
          </>
        ) : (
          <span className="deck-dim">{plane.reason}</span>
        )}
      </div>

      {lastDiff && (
        <div className="deck-section">
          <div className="deck-head">DIFF · {lastDiff.path}</div>
          <pre className="deck-diff">{lastDiff.diff}</pre>
        </div>
      )}

      <div className="deck-section">
        <div className="deck-head">
          TRANSCRIPT · {events.length} event{events.length === 1 ? "" : "s"}
        </div>
        <div className="deck-transcript">
          {events.map((e, i) => (
            <div
              key={i}
              className={`deck-line ${e.level === "error" ? "bad" : ""}`}
            >
              <span className="deck-dim">
                {new Date(e.ts * 1000).toLocaleTimeString()}{" "}
              </span>
              {e.type === "log"
                ? e.line
                : e.type === "file_diff"
                  ? `⇄ diff ${e.path}`
                  : e.type === "task_start"
                    ? "▶ task started"
                    : e.type === "task_done"
                      ? `■ task done — ${e.status}`
                      : e.type}
            </div>
          ))}
          <div ref={logEnd} />
        </div>
      </div>
      {err && <div className="deck-err">{err}</div>}
    </div>
  );
}
