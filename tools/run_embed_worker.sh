#!/usr/bin/env bash
# vault-embed — always-on embeddings server (nomic) replacing ollama for RAG.
# llama-server --embeddings on :8084, pinned to the R9700 (~0.4GB VRAM).
set -euo pipefail

LLAMA_DIR="${LLAMA_DIR:-$HOME/llm-workers/llama-b9870}"
PORT="${EMBED_PORT:-8084}"
MODEL="${EMBED_MODEL_PATH:-$HOME/llm-models/nomic-embed-text.gguf}"

export LD_LIBRARY_PATH="$LLAMA_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

DEV=$("$LLAMA_DIR/llama-server" --list-devices 2>/dev/null \
  | grep -oP '^\s*Vulkan\d+(?=: AMD Radeon AI PRO R9700)' | tr -d ' ' | head -1)
if [ -z "$DEV" ]; then
  echo "[vault-embed] FATAL: R9700 not found among Vulkan devices" >&2
  exit 1
fi

exec "$LLAMA_DIR/llama-server" \
  --device "$DEV" \
  --model "$MODEL" \
  --alias nomic-embed-text \
  --embeddings \
  --host 127.0.0.1 \
  --port "$PORT" \
  --ctx-size 2048 \
  --n-gpu-layers 999
