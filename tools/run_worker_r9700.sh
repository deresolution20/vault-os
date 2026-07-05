#!/usr/bin/env bash
# M5.1 — VAULT worker #1: llama.cpp VULKAN on the AMD R9700, OpenAI-compatible
# /v1 on :8081. PRD §3.1: single-GPU, pinned, own port — NEVER tensor-split
# across cards. Vulkan (not HIP) avoids the gfx1201 idle-power bug.
#
# VRAM contention (until the 7900 XTX lands): ollama shares this card
# (ornith:35b ≈ 27GB when hot). This script refuses to start if the card
# doesn't have enough free VRAM — wait for ollama's keep-alive to expire or
# `ollama stop <model>` first.
set -euo pipefail

LLAMA_DIR="${LLAMA_DIR:-$HOME/llm-workers/llama-b9870}"
PORT="${WORKER_R9700_PORT:-8081}"
# default model: qwen3-32b-abliterated from ~/llm-models (post-ollama).
# Swap at runtime with the vault /model command (sticky selection file).
MODEL="${MODEL_R9700:-$HOME/llm-models/qwen3-32b-abliterated-q4_k_m.gguf}"
ALIAS="${MODEL_R9700_ALIAS:-qwen3-32b-abliterated}"

# Runtime model switch (gpu-deck /model command) overrides everything:
# .tmp/worker-r9700.model is JSON {"path": ..., "alias": ...}
ROOT_TMP_SEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/.tmp/worker-r9700.model"
if [ -f "$ROOT_TMP_SEL" ]; then
  SEL_PATH=$(python3 -c "import json;print(json.load(open('$ROOT_TMP_SEL'))['path'])" 2>/dev/null || true)
  SEL_ALIAS=$(python3 -c "import json;print(json.load(open('$ROOT_TMP_SEL'))['alias'])" 2>/dev/null || true)
  if [ -n "$SEL_PATH" ] && [ -r "$SEL_PATH" ]; then
    MODEL="$SEL_PATH"
    ALIAS="${SEL_ALIAS:-selected}"
  fi
fi
CTX="${MODEL_R9700_CTX:-32768}"
MIN_FREE_GB=18

export LD_LIBRARY_PATH="$LLAMA_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

# Resolve the R9700's Vulkan index by NAME — device order can change across
# boots (the NVIDIA card enumerates first today).
DEV=$("$LLAMA_DIR/llama-server" --list-devices 2>/dev/null \
  | grep -oP '^\s*Vulkan\d+(?=: AMD Radeon AI PRO R9700)' | tr -d ' ' | head -1)
if [ -z "$DEV" ]; then
  echo "[worker-r9700] FATAL: R9700 not found among Vulkan devices" >&2
  exit 1
fi

# refuse to start into a VRAM squeeze
card=$(grep -l 0x1002 /sys/class/drm/card*/device/vendor 2>/dev/null | head -1 | xargs dirname)
if [ -n "$card" ] && [ -r "$card/mem_info_vram_used" ]; then
  free_gb=$(awk -v t="$(cat "$card/mem_info_vram_total")" -v u="$(cat "$card/mem_info_vram_used")" 'BEGIN{printf "%d", (t-u)/1e9}')
  if [ "$free_gb" -lt "$MIN_FREE_GB" ]; then
    echo "[worker-r9700] FATAL: only ${free_gb}GB VRAM free (< ${MIN_FREE_GB}GB) — ollama probably has a model resident. Try: ollama stop \$(ollama ps --format '{{.Name}}' 2>/dev/null | head -1) or wait for keep-alive." >&2
    exit 1
  fi
fi

echo "[worker-r9700] device=$DEV model=$ALIAS port=$PORT ctx=$CTX"
exec "$LLAMA_DIR/llama-server" \
  --device "$DEV" \
  --model "$MODEL" \
  --alias "$ALIAS" \
  --host 127.0.0.1 \
  --port "$PORT" \
  --ctx-size "$CTX" \
  --n-gpu-layers 999 \
  --jinja \
  --flash-attn on \
  --metrics
