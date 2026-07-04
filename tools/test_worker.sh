#!/usr/bin/env bash
# M5.1 AC test — worker serves completions AND the card idles at rest.
# Usage: tools/test_worker.sh [port]
set -euo pipefail
PORT="${1:-8081}"

echo "== /v1/models =="
curl -s -m 5 "http://127.0.0.1:$PORT/v1/models" | python3 -c "
import json, sys
d = json.load(sys.stdin)
for m in d.get('data', d.get('models', [])):
    print(' -', m.get('id') or m.get('name'))
"

echo "== completion =="
t0=$(date +%s.%N)
resp=$(curl -s -m 180 "http://127.0.0.1:$PORT/v1/chat/completions" \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"Write a Python one-liner that reverses a string. Reply with code only."}],"max_tokens":512,"temperature":0.2}')
t1=$(date +%s.%N)
printf '%s' "$resp" | python3 -c "
import json, sys
r = json.load(sys.stdin)
dt = float(sys.argv[2]) - float(sys.argv[1])
u = r.get('usage', {})
print('reply:', r['choices'][0]['message']['content'].strip()[:120])
ct = u.get('completion_tokens', 0)
print(f\"tokens: prompt={u.get('prompt_tokens')} completion={ct} · {ct/dt:.1f} tok/s wall\")
" "$t0" "$t1"

echo "== idle check (60s after completion; Vulkan must NOT pin the card) =="
sleep 60
card=$(grep -l 0x1002 /sys/class/drm/card*/device/vendor | head -1 | xargs dirname)
busy=$(cat "$card/gpu_busy_percent" 2>/dev/null || echo "n/a")
watts=$(awk '{printf "%.0f", $1/1e6}' "$card/hwmon"/hwmon*/power1_average 2>/dev/null | head -c 6 || echo "n/a")
echo "gpu_busy_percent=$busy power=${watts}W  (expect near-idle busy%, tens of watts)"
if [ "$busy" != "n/a" ] && [ "$busy" -gt 30 ]; then
  echo "WARN: card still busy at rest — investigate before trusting idle behavior" >&2
fi
