/**
 * M3 — the VAULT node cloud: real vault notes as glowing sprites, wikilinks
 * as faint neon edges, Blade Runner palette breathing, slow auto-orbit,
 * selective bloom (only the bright canvas blooms; DOM HUD stays crisp).
 */
import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import { EffectComposer, Bloom } from "@react-three/postprocessing";
import { HalfFloatType } from "three";
import * as THREE from "three";
import R3fForceGraph from "r3f-forcegraph";
import type { GraphNode, VaultGraph as GraphData } from "@vault/shared/events";
import { BG, hashId, makeGlowTexture, nodeColor } from "./palette";

/** Freeze layout after initial settle; re-heats when data changes (M3.5). */
const COOLDOWN_TICKS = 300;

export interface FgNode extends GraphNode {
  x?: number;
  y?: number;
  z?: number;
  __sprite?: THREE.Sprite;
  __seed?: number;
}

function Nodes({
  data,
  onNodeClick,
}: {
  data: GraphData;
  onNodeClick: (n: FgNode) => void;
}) {
  const fgRef = useRef<any>(null);
  const glowTex = useMemo(makeGlowTexture, []);
  const tmpColor = useMemo(() => new THREE.Color(), []);
  const sprites = useRef<Set<FgNode>>(new Set());

  // r3f-forcegraph mutates graphData; keep a stable copy per data change
  const graphData = useMemo(() => {
    sprites.current.clear();
    return {
      nodes: data.nodes.map((n) => ({ ...n })),
      links: data.links.map((l) => ({ ...l })),
    };
  }, [data]);

  const frameCount = useRef(0);
  useFrame(({ clock }) => {
    fgRef.current?.tickFrame();
    // the palette breathes at ~0.12rad/s — updating sprite colors every
    // 3rd frame is invisible and saves per-frame material churn
    if (frameCount.current++ % 3 !== 0) return;
    const t = clock.elapsedTime;
    for (const n of sprites.current) {
      if (!n.__sprite) continue;
      nodeColor(n.__seed!, t, !!n.unresolved, tmpColor);
      (n.__sprite.material as THREE.SpriteMaterial).color.copy(tmpColor);
    }
  });

  return (
    <R3fForceGraph
      ref={fgRef}
      graphData={graphData}
      cooldownTicks={COOLDOWN_TICKS}
      nodeThreeObject={(node: FgNode) => {
        node.__seed = hashId(node.id);
        const mat = new THREE.SpriteMaterial({
          map: glowTex,
          color: nodeColor(node.__seed, 0, !!node.unresolved, new THREE.Color()),
          transparent: true,
          blending: THREE.AdditiveBlending,
          depthWrite: false,
          toneMapped: false,
        });
        const sprite = new THREE.Sprite(mat);
        sprite.scale.setScalar(node.unresolved ? 6 : 10);
        node.__sprite = sprite;
        sprites.current.add(node);
        return sprite;
      }}
      linkColor={() => "#1b3a55"}
      linkOpacity={0.55}
      linkWidth={0.6}
      onNodeClick={(n: FgNode) => onNodeClick(n)}
    />
  );
}

export default function VaultGraphScene({
  data,
  onNodeClick,
}: {
  data: GraphData | null;
  onNodeClick: (n: FgNode) => void;
}) {
  return (
    <>
      <color attach="background" args={[BG]} />
      {data && <Nodes data={data} onNodeClick={onNodeClick} />}
      <OrbitControls
        autoRotate
        autoRotateSpeed={0.35}
        enableDamping
        dampingFactor={0.08}
      />
      <EffectComposer frameBufferType={HalfFloatType}>
        <Bloom
          mipmapBlur
          intensity={1.15}
          luminanceThreshold={0.25}
          luminanceSmoothing={0.2}
        />
      </EffectComposer>
    </>
  );
}
