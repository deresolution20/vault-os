/** M7.3 — hello-module panel: proves a drop-in module can render in the HUD. */
import type { PanelProps } from "../loader";

export default function HelloPanel({ events }: PanelProps) {
  const last = events[events.length - 1];
  return (
    <div className="module-panel">
      <div className="module-panel-title">HELLO-MODULE</div>
      <div className="module-panel-body">
        {last && last.type === "log" ? last.line : "no waves yet"}
      </div>
    </div>
  );
}
