/**
 * gpu-deck full view — /workflows-style live tree in its own window (#deck).
 * Polls /modules/gpu-deck/state every 2s. Light controls only.
 */
import { useEffect, useRef, useState } from "react";
import { openUrl } from "@tauri-apps/plugin-opener";
import { getConfig } from "../api";
import TaskDetail from "./TaskDetail";
import "./deck.css";

interface DeckState {
  ts: number;
  gpus: { id: string; name: string; vramUsedGB: number; vramTotalGB: number }[];
  workers: {
    id: string;
    gpu: string;
    unit: string;
    up: boolean;
    model?: string;
    activeSlots?: number;
    currentPrompt?: string;
  }[];
  throughput: Record<
    string,
    { liveTps: number; hourTokens: number; hourAvgTps: number }
  >;
  cloud: {
    model: string;
    requests: number;
    tokensIn: number;
    tokensOut: number;
    avgTps: number;
    avgLatencyMs: number;
    inFlight: number;
    approx: boolean;
  }[];
  runningTasks: {
    taskId: string;
    title: string;
    difficulty: string;
    worker: string;
    startedAt: number;
    plane: {
      linked: boolean;
      project?: string;
      milestone?: string;
      issue?: string;
      url?: string;
      reason?: string;
    };
  }[];
  history: {
    taskId: string;
    title?: string;
    status?: string;
    durationS?: number;
  }[];
  ledger: { localTokens: number; paidTokens: number };
}

const SPIN = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧"];

function vramBar(used: number, total: number): string {
  const w = 20;
  const filled = total > 0 ? Math.round((used / total) * w) : 0;
  return "█".repeat(filled) + "░".repeat(w - filled);
}

export default function DeckView({ docked = false }: { docked?: boolean }) {
  const [state, setState] = useState<DeckState | null>(null);
  const [err, setErr] = useState("");
  const [tick, setTick] = useState(0);
  const [drill, setDrill] = useState<string | null>(null);
  const cfg = useRef<{ apiUrl: string; token: string } | null>(null);

  useEffect(() => {
    let stop = false;
    const poll = async () => {
      if (stop) return;
      try {
        if (!cfg.current) cfg.current = await getConfig();
        const r = await fetch(
          `${cfg.current.apiUrl}/modules/gpu-deck/state`,
          { headers: { Authorization: `Bearer ${cfg.current.token}` } }
        );
        if (!r.ok) throw new Error(`state: ${r.status}`);
        setState(await r.json());
        setErr("");
      } catch (e) {
        setErr(String(e));
      }
      setTimeout(poll, 2000);
    };
    poll();
    const t = setInterval(() => setTick((n) => n + 1), 120);
    return () => {
      stop = true;
      clearInterval(t);
    };
  }, []);

  const control = async (unit: string, action: "start" | "stop") => {
    if (!cfg.current) return;
    await fetch(
      `${cfg.current.apiUrl}/modules/gpu-deck/workers/${unit}/${action}`,
      {
        method: "POST",
        headers: { Authorization: `Bearer ${cfg.current.token}` },
      }
    ).catch(() => {});
  };

  const rootClass = docked ? "deck-root deck-docked" : "deck-root";

  if (drill)
    return (
      <div className={rootClass}>
        <TaskDetail taskId={drill} onBack={() => setDrill(null)} />
      </div>
    );

  if (!state)
    return (
      <div className={rootClass}>
        <div className="deck-title">VAULT · GPU DECK</div>
        <div className="deck-err">{err || "connecting…"}</div>
      </div>
    );

  const spinner = SPIN[tick % SPIN.length];

  return (
    <div className={rootClass}>
      <div className="deck-title">
        GPU DECK{" "}
        <span className="deck-dim">
          local {state.ledger.localTokens} tok · paid {state.ledger.paidTokens}{" "}
          tok
        </span>
      </div>

      {state.gpus.map((g) => {
        const worker = state.workers.find((w) => w.gpu === g.id);
        const tp = state.throughput?.[g.id];
        return (
          <div key={g.id} className="deck-gpu">
            <div className="deck-gpu-head">
              ◉ {g.name}{" "}
              <span className="deck-vram">
                {vramBar(g.vramUsedGB, g.vramTotalGB)} {g.vramUsedGB}/
                {g.vramTotalGB} GB
              </span>
            </div>
            {tp && (
              <div className="deck-line deck-tps">
                ⚡ {tp.liveTps} tok/s
                <span className="deck-dim">
                  {" "}
                  · 1h Ø {tp.hourAvgTps} tok/s · {tp.hourTokens.toLocaleString()} tok
                </span>
              </div>
            )}
            {worker && (
              <div className="deck-line">
                ├─ vault-worker{" "}
                {worker.up ? (
                  <>
                    <span className="ok">● up</span> · {worker.model} ·{" "}
                    {worker.activeSlots ?? 0} slot(s) busy
                    {worker.currentPrompt && (
                      <span className="deck-dim">
                        {" "}
                        · “{worker.currentPrompt.slice(0, 60)}…”
                      </span>
                    )}
                  </>
                ) : (
                  <span className="deck-dim">○ down</span>
                )}{" "}
                <button
                  className="deck-btn"
                  onClick={() => control(worker.unit, worker.up ? "stop" : "start")}
                >
                  {worker.up ? "stop" : "start"}
                </button>
              </div>
            )}
          </div>
        );
      })}


      <div className="deck-section">
        <div className="deck-head">CLOUD ORCHESTRATOR · ollama.com</div>
        {(!state.cloud || state.cloud.length === 0) && (
          <div className="deck-line deck-dim">└─ no traffic in the last hour</div>
        )}
        {state.cloud?.map((c) => (
          <div key={c.model} className="deck-line">
            {c.inFlight > 0 ? spinner : "├─"} <b>{c.model}</b>{" "}
            <span className="deck-dim">
              {c.requests} req · in {c.tokensIn.toLocaleString()} / out{" "}
              {c.tokensOut.toLocaleString()}
              {c.approx && "≈"} tok · {c.avgTps} tok/s · {c.avgLatencyMs}ms
            </span>
          </div>
        ))}
        {state.throughput?.["paid-api"] &&
          state.throughput["paid-api"].hourTokens > 0 && (
            <div className="deck-line deck-dim">
              └─ anthropic fallback · {state.throughput["paid-api"].hourTokens}{" "}
              tok this hour
            </div>
          )}
      </div>

      <div className="deck-section">
        <div className="deck-head">RUNNING</div>
        {state.runningTasks.length === 0 && (
          <div className="deck-line deck-dim">└─ idle</div>
        )}
        {state.runningTasks.map((t) => (
          <div
            key={t.taskId}
            className="deck-drillable"
            onClick={() => setDrill(t.taskId)}
            title="drill down"
          >
            <div className="deck-line">
              {spinner} <b>{t.taskId}</b> {t.title}{" "}
              <span className="deck-dim">
                [{t.difficulty} · {t.worker} ·{" "}
                {Math.round(state.ts - t.startedAt)}s]
              </span>
            </div>
            <div className="deck-line deck-plane">
              │ {t.plane.linked ? (
                <>
                  {t.plane.project} › {String(t.plane.milestone)} ›{" "}
                  {t.plane.issue}{" "}
                  {t.plane.url && (
                    <button
                      className="deck-btn"
                      onClick={(e) => {
                        e.stopPropagation(); // don't also trigger drill-down
                        openUrl(t.plane.url!).catch(console.error);
                      }}
                    >
                      open ↗
                    </button>
                  )}
                </>
              ) : (
                <span className="deck-dim">{t.plane.reason}</span>
              )}
            </div>
          </div>
        ))}
      </div>

      <div className="deck-section">
        <div className="deck-head">HISTORY</div>
        {state.history.length === 0 && (
          <div className="deck-line deck-dim">└─ none yet</div>
        )}
        {state.history.map((h, i) => (
          <div
            key={i}
            className="deck-line deck-drillable"
            onClick={() => setDrill(h.taskId)}
            title="drill down"
          >
            {h.status === "success" ? (
              <span className="ok">✓</span>
            ) : (
              <span className="bad">✗</span>
            )}{" "}
            {h.taskId} {h.title ?? ""}{" "}
            <span className="deck-dim">{h.durationS}s</span>
          </div>
        ))}
      </div>

      {err && <div className="deck-err">{err}</div>}
    </div>
  );
}
