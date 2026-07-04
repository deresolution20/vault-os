/**
 * M1.1 — Bloom spike scene.
 * ~5k instanced glowing nodes + selective-ish bloom (luminance threshold),
 * color-shift over time + slow auto-orbit. This is the GATING test for
 * Tauri/WebKitGTK on the real AMD box (PRD §3.3, research addendum §4).
 */
import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import { EffectComposer, Bloom } from "@react-three/postprocessing";
import * as THREE from "three";
import { HalfFloatType } from "three";

export const NODE_COUNT = 5000;

function Nodes() {
  const meshRef = useRef<THREE.InstancedMesh>(null!);
  const color = useMemo(() => new THREE.Color(), []);

  // static positions in a galaxy-ish cloud + per-node hue offset
  const { positions, hues } = useMemo(() => {
    const positions: THREE.Vector3[] = [];
    const hues: number[] = [];
    // deterministic LCG so every run measures the same scene
    let seed = 42;
    const rand = () => (seed = (seed * 1664525 + 1013904223) >>> 0) / 2 ** 32;
    for (let i = 0; i < NODE_COUNT; i++) {
      const r = 30 * Math.cbrt(rand());
      const theta = rand() * Math.PI * 2;
      const phi = Math.acos(2 * rand() - 1);
      positions.push(
        new THREE.Vector3(
          r * Math.sin(phi) * Math.cos(theta),
          r * Math.sin(phi) * Math.sin(theta) * 0.6,
          r * Math.cos(phi)
        )
      );
      hues.push(rand());
    }
    return { positions, hues };
  }, []);

  useFrame(({ clock }) => {
    const mesh = meshRef.current;
    if (!mesh) return;
    const t = clock.elapsedTime;
    const m = new THREE.Matrix4();
    if (!mesh.userData.placed) {
      positions.forEach((p, i) => {
        m.setPosition(p);
        mesh.setMatrixAt(i, m);
      });
      mesh.instanceMatrix.needsUpdate = true;
      mesh.userData.placed = true;
    }
    // color-shift over time (M3.3 workload, exercised here for realism)
    for (let i = 0; i < NODE_COUNT; i++) {
      color.setHSL((hues[i] + t * 0.03) % 1, 0.9, 0.6);
      mesh.setColorAt(i, color);
    }
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  });

  return (
    <instancedMesh ref={meshRef} args={[undefined, undefined, NODE_COUNT]}>
      <sphereGeometry args={[0.18, 8, 8]} />
      <meshBasicMaterial toneMapped={false} />
    </instancedMesh>
  );
}

export default function BloomSpike() {
  return (
    <>
      <color attach="background" args={["#05060a"]} />
      <Nodes />
      <OrbitControls autoRotate autoRotateSpeed={0.6} enableDamping={false} />
      <EffectComposer frameBufferType={HalfFloatType}>
        <Bloom
          mipmapBlur
          intensity={1.4}
          luminanceThreshold={0.2}
          luminanceSmoothing={0.15}
        />
      </EffectComposer>
    </>
  );
}
