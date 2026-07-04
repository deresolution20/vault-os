/** gpu-deck compact HUD panel: one line per GPU, click to open the full deck. */
import { useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { getConfig } from "../../api";
import type { PanelProps } from "../loader";

interface Mini {
  gpus: { id: string; name: string; vramUsedGB: number; vramTotalGB: number }[];
  workers: { gpu: string; up: boolean; model?: string; activeSlots?: number }[];
  runningTasks: { taskId: string }[];
}

export default function GpuDeckPanel(_: PanelProps) {
  const [mini, setMini] = useState<Mini | null>(null);
  const cfg = useRef<{ apiUrl: string; token: string } | null>(null);

  useEffect(() => {
    let stop = false;
    const poll = async () => {
      if (stop) return;
      try {
        if (!cfg.current) cfg.current = await getConfig();
        const r = await fetch(`${cfg.current.apiUrl}/modules/gpu-deck/state`, {
          headers: { Authorization: `Bearer ${cfg.current.token}` },
        });
        if (r.ok) setMini(await r.json());
      } catch {
        /* next poll */
      }
      setTimeout(poll, 3000);
    };
    poll();
    return () => {
      stop = true;
    };
  }, []);

  return (
    <div
      className="module-panel gpu-deck-mini"
      onClick={() => invoke("open_deck").catch(console.error)}
      title="open GPU deck"
    >
      <div className="module-panel-title">GPU DECK ↗</div>
      {mini ? (
        mini.gpus.map((g) => {
          const w = mini.workers.find((x) => x.gpu === g.id);
          const busy = mini.runningTasks.length;
          return (
            <div key={g.id} className="deck-mini-line">
              {g.id} {g.vramUsedGB}/{g.vramTotalGB}G{" "}
              {w?.up ? `● ${w.model}` : "○"}
              {busy > 0 && ` · ${busy} task${busy > 1 ? "s" : ""}`}
            </div>
          );
        })
      ) : (
        <div className="deck-mini-line">…</div>
      )}
    </div>
  );
}
