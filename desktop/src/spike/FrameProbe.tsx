/**
 * M1.2 — startup frame-time probe.
 * WebKitGTK reports "Apple GPU" for every renderer (fingerprint protection),
 * so software-render fallback MUST be detected empirically: measure ms/frame
 * with bloom active. Warmup 120 frames, then sample 600.
 */
import { useRef } from "react";
import { useFrame, useThree } from "@react-three/fiber";

export interface SpikeResult {
  nodeCount: number;
  frames: number;
  avgMs: number;
  p95Ms: number;
  fps: number;
  softwareRenderSuspected: boolean;
  devicePixelRatio: number;
  canvas: { width: number; height: number };
  userAgent: string;
}

const WARMUP = 120;
const SAMPLES = 600;
/** RADV on an R9700 holds vsync easily; the ambient FrameGovernor caps at
 * 30fps, so the alarm threshold sits below that. True software rendering
 * at 4K+bloom lands under 10fps — still caught with margin. */
const SOFTWARE_RENDER_FPS_THRESHOLD = 20;

export default function FrameProbe({
  onDone,
}: {
  onDone: (r: SpikeResult) => void;
}) {
  const { gl } = useThree();
  const state = useRef({ n: 0, times: [] as number[], last: 0, done: false });

  useFrame(() => {
    const s = state.current;
    if (s.done) return;
    const now = performance.now();
    if (s.last > 0) {
      s.n += 1;
      if (s.n > WARMUP) s.times.push(now - s.last);
    }
    s.last = now;
    if (s.times.length >= SAMPLES) {
      s.done = true;
      const sorted = [...s.times].sort((a, b) => a - b);
      const avgMs = s.times.reduce((a, b) => a + b, 0) / s.times.length;
      const fps = 1000 / avgMs;
      onDone({
        nodeCount: 5000,
        frames: s.times.length,
        avgMs: +avgMs.toFixed(2),
        p95Ms: +sorted[Math.floor(sorted.length * 0.95)].toFixed(2),
        fps: +fps.toFixed(1),
        softwareRenderSuspected: fps < SOFTWARE_RENDER_FPS_THRESHOLD,
        devicePixelRatio: window.devicePixelRatio,
        canvas: {
          width: gl.domElement.width,
          height: gl.domElement.height,
        },
        userAgent: navigator.userAgent,
      });
    }
  });

  return null;
}
