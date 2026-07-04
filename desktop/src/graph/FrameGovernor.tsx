/**
 * Ambient frame governor: with Canvas frameloop="demand", this drives the
 * render loop at a capped rate (30fps) instead of vsync. User interaction
 * (OrbitControls change events) still invalidates at full rate, so dragging
 * feels 60fps while the idle HUD costs half the compositor/copy work —
 * matters double here because the scene renders on the R9700 and is copied
 * to the 4060 Ti for display. Stops entirely while the window is hidden.
 */
import { useEffect } from "react";
import { useThree } from "@react-three/fiber";

export default function FrameGovernor({ fps = 30 }: { fps?: number }) {
  const invalidate = useThree((s) => s.invalidate);

  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | null = null;
    const start = () => {
      if (!timer) timer = setInterval(() => invalidate(), 1000 / fps);
    };
    const stop = () => {
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
    };
    const onVis = () => (document.hidden ? stop() : start());
    document.addEventListener("visibilitychange", onVis);
    start();
    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVis);
    };
  }, [fps, invalidate]);

  return null;
}
