/**
 * Blade Runner palette (the operator's directive 2026-07-03): neon cyan/teal and
 * magenta/pink glow on a near-black blue base, holographic amber for HUD
 * accents. Color drift stays INSIDE this palette — no full-rainbow cycling.
 */
import * as THREE from "three";

export const BG = "#04060c";
export const AMBER = "#ffb347";

// node glow anchors (hue in [0,1] HSL)
export const CYAN_HUE = 0.52; // #00e5ff-ish
export const MAGENTA_HUE = 0.87; // #ff2bd6-ish
export const VIOLET_HUE = 0.72; // unresolved / ghost notes

/**
 * Per-node color: each node sits at a fixed blend between cyan and magenta
 * (seeded by its id hash) and breathes slowly around that point over time.
 * Ghost (unresolved) nodes are dim violet.
 */
export function nodeColor(
  seed: number,
  t: number,
  unresolved: boolean,
  out: THREE.Color
): THREE.Color {
  if (unresolved) {
    out.setHSL(VIOLET_HUE, 0.55, 0.32);
    return out;
  }
  const mix = 0.5 + 0.5 * Math.sin(seed * 6.283 + t * 0.12);
  const hue =
    CYAN_HUE + (MAGENTA_HUE - CYAN_HUE) * (0.15 + 0.7 * mix);
  out.setHSL(hue, 1.0, 0.62);
  return out;
}

export function hashId(id: string): number {
  let h = 2166136261;
  for (let i = 0; i < id.length; i++) {
    h ^= id.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return ((h >>> 0) % 1000) / 1000;
}

/** Soft radial glow texture for node sprites (drawn once, shared). */
export function makeGlowTexture(): THREE.Texture {
  const size = 128;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext("2d")!;
  const g = ctx.createRadialGradient(
    size / 2, size / 2, 0,
    size / 2, size / 2, size / 2
  );
  g.addColorStop(0, "rgba(255,255,255,1)");
  g.addColorStop(0.25, "rgba(255,255,255,0.6)");
  g.addColorStop(0.6, "rgba(255,255,255,0.12)");
  g.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, size, size);
  const tex = new THREE.CanvasTexture(canvas);
  tex.needsUpdate = true;
  return tex;
}
