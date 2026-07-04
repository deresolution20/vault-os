/** M6.3 — Grafana GPU panels. RESOURCE metrics, never an activity signal. */
import type { PanelProps } from "../loader";

export default function GrafanaPanel({ module }: PanelProps) {
  const url = (module?.config?.embedUrl as string) || "";
  return (
    <div className="module-panel grafana-panel">
      <div className="module-panel-title">GPU RESOURCE · GRAFANA</div>
      {url ? (
        <iframe src={url} title="grafana" className="grafana-frame" />
      ) : (
        <div className="module-panel-body">
          set GRAFANA_EMBED_URL in .env to embed VRAM/temp panels
        </div>
      )}
    </div>
  );
}
