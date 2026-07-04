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
# default model: qwen3 32B q4_K_M GGUF reused from the ollama store
# (read-only). NOTE: qwen3.6/ornith blobs use ollama-fork archs (qwen35)
# that upstream llama.cpp can't load — stick to arch=qwen3 models here.
# Swap via MODEL_R9700 env or projects/vault-os/.env when a dedicated coding
# model is chosen.
MODEL="${MODEL_R9700:-/var/lib/ollama-r9700/models/blobs/sha256-a27a92cf139a68efcbb267c6af6d20bb8f3feddc700f3b03cd8d41f4dc443348}"
ALIAS="${MODEL_R9700_ALIAS:-qwen3-32b}"
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
