#!/usr/bin/env bash
# M1 bloom spike runner — launches the Tauri app fullscreen on the real AMD
# box, waits for the frame-probe result, prints it, and exits.
# Constraint (PRD §3.5): never set WEBKIT_DISABLE_DMABUF_RENDERER /
# WEBKIT_DISABLE_COMPOSITING_MODE here — they force software rendering.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESULT="$ROOT/docs/M1-spike-result.json"
rm -f "$RESULT"

export PATH="$HOME/.cargo/bin:$PATH"
export SPIKE_RESULT_PATH="$RESULT"
export SPIKE_AUTOEXIT=1
# Opt in to the WebGL GPU process (research addendum: assume opt-in needed)
export WEBKIT_FEATURES="${WEBKIT_FEATURES:-UseGPUProcessForWebGL}"

cd "$ROOT/desktop"
echo "[spike] building + launching (first Rust build takes several minutes)…"
pnpm tauri dev &
TAURI_PID=$!

# wait up to 15 min for the probe to write its result (600 frames + build)
for _ in $(seq 1 900); do
  [ -f "$RESULT" ] && break
  kill -0 "$TAURI_PID" 2>/dev/null || break
  sleep 1
done

if [ -f "$RESULT" ]; then
  echo "[spike] result:"
  cat "$RESULT"
else
  echo "[spike] FAILED — no result file produced" >&2
  kill "$TAURI_PID" 2>/dev/null || true
  exit 1
fi
# tauri dev exits itself via SPIKE_AUTOEXIT; reap the wrapper just in case
wait "$TAURI_PID" 2>/dev/null || true
