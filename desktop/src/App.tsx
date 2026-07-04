import { useCallback, useEffect, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { invoke } from "@tauri-apps/api/core";
import type { VaultEvent, VaultGraph } from "@vault/shared/events";
import { fetchGraph, subscribeEvents } from "./api";
import VaultGraphScene, { FgNode } from "./graph/VaultGraph";
import NotePanel from "./panels/NotePanel";
import FrameProbe, { SpikeResult } from "./spike/FrameProbe";
import "./App.css";

export default function App() {
  const [graph, setGraph] = useState<VaultGraph | null>(null);
  const [selected, setSelected] = useState<FgNode | null>(null);
  const [wsUp, setWsUp] = useState(false);
  const [probe, setProbe] = useState<SpikeResult | null>(null);
  const [lastEvent, setLastEvent] = useState<string>("");

  const loadGraph = useCallback(() => {
    fetchGraph().then(setGraph).catch((e) => console.error("graph:", e));
  }, []);

  // initial load — retry until the sidecar API is up
  useEffect(() => {
    let tries = 0;
    const t = setInterval(() => {
      tries += 1;
      fetchGraph()
        .then((g) => {
          setGraph(g);
          clearInterval(t);
        })
        .catch(() => {
          if (tries > 30) clearInterval(t);
        });
    }, 1000);
    return () => clearInterval(t);
  }, []);

  // live growth: vault changes re-pull the graph (M2.3 → M3)
  useEffect(
    () =>
      subscribeEvents((e: VaultEvent) => {
        setLastEvent(`${e.type} · ${"nodeId" in e ? e.nodeId : e.source}`);
        if (e.type === "node_update") loadGraph();
      }, setWsUp),
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
      <Canvas camera={{ position: [0, 40, 220], fov: 55 }} dpr={[1, 2]}>
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

      <NotePanel node={selected} onClose={() => setSelected(null)} />
    </div>
  );
}
