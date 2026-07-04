import { Suspense, useCallback, useEffect, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { invoke } from "@tauri-apps/api/core";
import { getCurrentWindow } from "@tauri-apps/api/window";
import type { VaultEvent, VaultGraph } from "@vault/shared/events";
import { fetchGraph, fetchModules, subscribeEvents } from "./api";
import DeckView from "./deck/DeckView";
import FrameGovernor from "./graph/FrameGovernor";
import VaultGraphScene, { FgNode } from "./graph/VaultGraph";
import { ModuleManifestEntry, panelRegistry } from "./modules/loader";
import NotePanel from "./panels/NotePanel";
import FrameProbe, { SpikeResult } from "./spike/FrameProbe";
import "./App.css";

export default function App() {
  const [graph, setGraph] = useState<VaultGraph | null>(null);
  const [selected, setSelected] = useState<FgNode | null>(null);
  const [wsUp, setWsUp] = useState(false);
  const [probe, setProbe] = useState<SpikeResult | null>(null);
  const [lastEvent, setLastEvent] = useState<string>("");
  const [modules, setModules] = useState<ModuleManifestEntry[]>([]);
  const [moduleEvents, setModuleEvents] = useState<
    Record<string, VaultEvent[]>
  >({});
  const [vitals, setVitals] = useState<Record<string, number>>({});
  // frameloop="demand" + FrameGovernor: 30fps ambient, 60fps while
  // interacting, zero while hidden (governor stops its interval)

  const loadGraph = useCallback(() => {
    fetchGraph().then(setGraph).catch((e) => console.error("graph:", e));
  }, []);

  // initial load — keep retrying until the sidecar API answers; surface the
  // last error in the HUD instead of a silent "connecting…" forever
  const [apiError, setApiError] = useState<string>("");
  useEffect(() => {
    let stop = false;
    const tick = () => {
      if (stop) return;
      fetchGraph()
        .then((g) => {
          setGraph(g);
          setApiError("");
        })
        .catch((e) => {
          setApiError(String(e));
          setTimeout(tick, 2000);
        });
    };
    tick();
    return () => {
      stop = true;
    };
  }, []);

  // escape hatches: Esc leaves fullscreen, F11 toggles it, ctrl+Q quits
  useEffect(() => {
    const w = getCurrentWindow();
    const onKey = async (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        // when a deck drill-down is open, Esc backs out of it instead
        if (document.querySelector(".deck-detail")) return;
        await w.setFullscreen(false);
      }
      else if (e.key === "F11") await w.setFullscreen(!(await w.isFullscreen()));
      else if (e.key.toLowerCase() === "q" && e.ctrlKey) await invoke("quit_app");
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // live growth: vault changes re-pull the graph (M2.3 → M3); also re-pull
  // whenever the bus (re)connects — the API is definitely up at that moment
  useEffect(
    () =>
      subscribeEvents(
        (e: VaultEvent) => {
          setLastEvent(`${e.type} · ${"nodeId" in e ? e.nodeId : e.source}`);
          if (e.type === "node_update") loadGraph();
          if (e.type === "system_vital")
            setVitals((v) => ({ ...v, [e.metric]: e.value }));
          // route to the emitting module's panel buffer (last 50 per module)
          setModuleEvents((prev) => ({
            ...prev,
            [e.source]: [...(prev[e.source] ?? []), e].slice(-50),
          }));
        },
        (up) => {
          setWsUp(up);
          if (up) {
            loadGraph();
            fetchModules().then(setModules).catch(console.error);
          }
        }
      ),
    [loadGraph]
  );

  // M1.2 canary: report startup render performance every launch
  const handleProbe = useCallback((r: SpikeResult) => {
    setProbe(r);
    if (r.softwareRenderSuspected)
      console.error("SOFTWARE RENDER SUSPECTED", r);
    invoke("report_spike", { result: JSON.stringify(r, null, 2) }).catch(
      () => {}
    );
  }, []);

  return (
    <div className="hud-root">
      <Canvas
        camera={{ position: [0, 40, 220], fov: 55 }}
        dpr={[1, 1.5]}
        frameloop="demand"
      >
        <FrameGovernor fps={30} />
        <VaultGraphScene data={graph} onNodeClick={setSelected} />
        <FrameProbe onDone={handleProbe} />
      </Canvas>

      <div className="hud-overlay">
        <span className="hud-title">VAULT</span>
        <span className="hud-line">
          {graph
            ? `${graph.nodes.length} nodes · ${graph.links.length} links`
            : "connecting to hermes…"}
        </span>
        {!graph && apiError && <span className="bad">{apiError}</span>}
        <span className="hud-hint">esc window · F11 fullscreen · ctrl+Q quit</span>
        <span className="hud-line">
          bus {wsUp ? "● live" : "○ down"}
          {lastEvent && ` · ${lastEvent}`}
        </span>
        {probe && (
          <span className={probe.softwareRenderSuspected ? "bad" : "hud-line"}>
            {probe.fps} fps
            {probe.softwareRenderSuspected && " ⚠ SOFTWARE RENDER"}
          </span>
        )}
      </div>

      <aside className="deck-dock">
        <button
          className="deck-btn deck-popout"
          onClick={() => invoke("open_deck").catch(console.error)}
        >
          pop out ↗
        </button>
        <DeckView docked />
      </aside>

      <div className="vitals-strip">
        {Object.entries(vitals).map(([k, v]) => (
          <span key={k} className="vital">
            {k.replace(/_/g, " ")} <b>{v}</b>
          </span>
        ))}
        <span className="vital vital-note">resource · not activity</span>
      </div>

      <div className="module-dock">
        {modules
          .filter((m) => m.panel && panelRegistry[m.panel])
          .map((m) => {
            const Panel = panelRegistry[m.panel!];
            return (
              <Suspense key={m.id} fallback={null}>
                <Panel events={moduleEvents[m.id] ?? []} module={m} />
              </Suspense>
            );
          })}
      </div>

      <NotePanel node={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
