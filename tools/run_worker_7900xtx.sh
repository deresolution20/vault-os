#!/usr/bin/env bash
# VAULT worker #2: llama.cpp Vulkan on the AMD Radeon RX 7900 XTX.
# OpenAI-compatible /v1 on :8082. Single-GPU pinned; never tensor-split.
set -euo pipefail

LLAMA_DIR="${LLAMA_DIR:-$HOME/llm-workers/llama-b9870}"
PORT="${WORKER_7900XTX_PORT:-8082}"
MODEL="${MODEL_7900XTX:-$HOME/llm-models/Qwen3.6-35B-A3B-UD-IQ3_S.gguf}"
ALIAS="${MODEL_7900XTX_ALIAS:-qwen3.6-35b-a3b}"
CTX="${MODEL_7900XTX_CTX:-16384}"
DEFAULT_EXTRA_ARGS=(--chat-template-kwargs '{"enable_thinking":false}')
EXTRA_ARGS=("${DEFAULT_EXTRA_ARGS[@]}")

# Runtime model switch (gpu-deck /model command) overrides defaults.
# .tmp/worker-7900xtx.model is JSON {"path": ..., "alias": ..., "args": [...]}.
ROOT_TMP_SEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/.tmp/worker-7900xtx.model"
if [ -f "$ROOT_TMP_SEL" ]; then
  SEL_PATH=$(python3 -c "import json;print(json.load(open('$ROOT_TMP_SEL'))['path'])" 2>/dev/null || true)
  SEL_ALIAS=$(python3 -c "import json;print(json.load(open('$ROOT_TMP_SEL'))['alias'])" 2>/dev/null || true)
  if [ -n "$SEL_PATH" ] && [ -r "$SEL_PATH" ]; then
    MODEL="$SEL_PATH"
    ALIAS="${SEL_ALIAS:-selected}"
    EXTRA_ARGS=()
    while IFS= read -r arg; do
      [ -n "$arg" ] && EXTRA_ARGS+=("$arg")
    done < <(python3 -c "import json;[print(a) for a in json.load(open('$ROOT_TMP_SEL')).get('args',[])]" 2>/dev/null || true)
  fi
fi

export LD_LIBRARY_PATH="$LLAMA_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

# Resolve by device name; Vulkan indices can change across boots.
DEV=$("$LLAMA_DIR/llama-server" --list-devices 2>/dev/null \
  | grep -oP '^\s*Vulkan\d+(?=: Radeon RX 7900 XTX)' | tr -d ' ' | head -1)
if [ -z "$DEV" ]; then
  echo "[worker-7900xtx] FATAL: Radeon RX 7900 XTX not found among Vulkan devices" >&2
  exit 1
fi

echo "[worker-7900xtx] device=$DEV model=$ALIAS port=$PORT ctx=$CTX"
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
  --metrics \
  ${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}
