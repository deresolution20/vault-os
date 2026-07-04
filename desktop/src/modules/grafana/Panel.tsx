/** M6.3 — Grafana GPU panels. RESOURCE metrics, never an activity signal.
 * Grafana Cloud denies iframes (X-Frame-Options), so the dashboard opens in
 * a dedicated child window via the open_vitals Rust command. */
import { useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { PanelProps } from "../loader";

export default function GrafanaPanel({ module }: PanelProps) {
  const configured = Boolean(module?.config?.embedUrl);
  const [err, setErr] = useState("");

  return (
    <div className="module-panel grafana-panel">
      <div className="module-panel-title">GPU RESOURCE · GRAFANA</div>
      {configured ? (
        <button
          className="vitals-button"
          onClick={() => invoke("open_vitals").catch((e) => setErr(String(e)))}
        >
          open vitals window ↗
        </button>
      ) : (
        <div className="module-panel-body">
          set GRAFANA_EMBED_URL in .env to enable
        </div>
      )}
      {err && <div className="module-panel-body bad">{err}</div>}
    </div>
  );
}
