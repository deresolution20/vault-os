#!/usr/bin/env bash
# VAULT worker #2 (interim): llama.cpp VULKAN on the NVIDIA 4060 Ti, OpenAI
# /v1 on :8082 — the junior lane until the 7900 XTX lands (then this card
# can retire or stay as a third lane). Single-GPU pinned (PRD §3.1 holds).
# NOTE: this card also drives the display — expect some desktop contention.
set -euo pipefail

LLAMA_DIR="${LLAMA_DIR:-$HOME/llm-workers/llama-b9870}"
PORT="${WORKER_4060TI_PORT:-8082}"
# default: qwen3:14b q4 (9.3GB) — fits 16GB with display + modest context
MODEL="${MODEL_4060TI:-/var/lib/ollama-r9700/models/blobs/sha256-a8cc1361f3145dc01f6d77c6c82c9116b9ffe3c97b34716fe20418455876c40e}"
ALIAS="${MODEL_4060TI_ALIAS:-qwen3:14b}"
CTX="${MODEL_4060TI_CTX:-16384}"
MIN_FREE_GB=10

# Runtime model switch (gpu-deck /model command) overrides everything
ROOT_TMP_SEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/.tmp/worker-4060ti.model"
if [ -f "$ROOT_TMP_SEL" ]; then
  SEL_PATH=$(python3 -c "import json;print(json.load(open('$ROOT_TMP_SEL'))['path'])" 2>/dev/null || true)
  SEL_ALIAS=$(python3 -c "import json;print(json.load(open('$ROOT_TMP_SEL'))['alias'])" 2>/dev/null || true)
  if [ -n "$SEL_PATH" ] && [ -r "$SEL_PATH" ]; then
    MODEL="$SEL_PATH"
    ALIAS="${SEL_ALIAS:-selected}"
  fi
fi

export LD_LIBRARY_PATH="$LLAMA_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

DEV=$("$LLAMA_DIR/llama-server" --list-devices 2>/dev/null \
  | grep -oP '^\s*Vulkan\d+(?=: NVIDIA GeForce RTX 4060 Ti)' | tr -d ' ' | head -1)
if [ -z "$DEV" ]; then
  echo "[worker-4060ti] FATAL: 4060 Ti not found among Vulkan devices" >&2
  exit 1
fi

# refuse to start into a VRAM squeeze (display + ollama share this card)
free_gb=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null | head -1)
if [ -n "$free_gb" ] && [ "$((free_gb / 1024))" -lt "$MIN_FREE_GB" ]; then
  echo "[worker-4060ti] FATAL: only $((free_gb / 1024))GB VRAM free (< ${MIN_FREE_GB}GB) — display/ollama are using the card." >&2
  exit 1
fi

echo "[worker-4060ti] device=$DEV model=$ALIAS port=$PORT ctx=$CTX"
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
