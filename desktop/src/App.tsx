import { useCallback, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { invoke } from "@tauri-apps/api/core";
import BloomSpike from "./spike/BloomSpike";
import FrameProbe, { SpikeResult } from "./spike/FrameProbe";
import "./App.css";

/**
 * Step-One shell. Currently hosts the M1 bloom spike; the HUD layout and
 * graph (M3) replace this after the M1.3 GO decision.
 */
export default function App() {
  const [result, setResult] = useState<SpikeResult | null>(null);

  const handleDone = useCallback((r: SpikeResult) => {
    setResult(r);
    invoke("report_spike", { result: JSON.stringify(r, null, 2) }).catch(
      (e) => console.error("report_spike failed:", e)
    );
  }, []);

  return (
    <div className="hud-root">
      <Canvas camera={{ position: [0, 8, 55], fov: 60 }} dpr={[1, 2]}>
        <BloomSpike />
        <FrameProbe onDone={handleDone} />
      </Canvas>
      <div className="hud-overlay">
        <span className="hud-title">VAULT · M1 BLOOM SPIKE</span>
        {result ? (
          <span className={result.softwareRenderSuspected ? "bad" : "good"}>
            {result.fps} FPS avg · {result.avgMs} ms/frame · p95 {result.p95Ms}{" "}
            ms ·{" "}
            {result.softwareRenderSuspected
              ? "⚠ SOFTWARE RENDER SUSPECTED"
              : "hardware render OK"}
          </span>
        ) : (
          <span>measuring…</span>
        )}
      </div>
    </div>
  );
}
