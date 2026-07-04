# VAULT — Voice-Activated Unified Logic Terminal (Step One)

Local AI-OS: Hermes API (graph/RAG/writes/events), two AMD GPU model workers,
Plane/Grafana telemetry — and two front-ends:

- **`vault` (the daily driver)** — Claude-Code-style Textual TUI: GPU deck
  with live tok/s, cloud-orchestrator lane, task drill-down, and a command
  deck (`/run`, `/hermes`, `/ask`, Esc to cancel). Zero GPU, SSH-friendly.
  Decision + research: `docs/TUI-DECISION-2026-07-04.md`.
- **Tauri HUD (optional eye-candy)** — the glowing 3D node cloud of the
  Obsidian vault with live panels; launch it when you want the wall display
  (`pnpm tauri dev`), costs nothing when closed.

**Source of truth:** `docs/PRD-vault-os.md` (modules, tasks, ACs, build order)
and `docs/RESEARCH-2026-07-03-vault-os-architecture.md` (verified tech
choices + ROCm/Tauri addendum). Hard constraints: PRD §3.

## Layout (M0.1)

```
desktop/    Tauri v2 + React + R3F front-end (the HUD)
  src/spike/           M1 bloom spike (gating test, PRD §3.3)
  src/modules/<id>/    module panels (M7 contract)
  src-tauri/           Rust shell: window, tray, sidecar, FS watch
api/        Hermes API — FastAPI (REST + WS /ws/events)
  src/vault_api/       events.py (schema mirror) · modules.py (M7 registry)
                       bus.py (WS fan-out) · config.py (.env loader)
indexer/    vault → graph JSON + sqlite-vec RAG index (M2)
modules/    backend module implementations (M7)
shared/     events.ts — single source of truth for the event schema
docs/       PRD, research, module contract, decision notes
```

## Dev quickstart

```bash
cp .env.example .env         # set VAULT_PATH etc.
pnpm install                 # workspace: desktop + shared
cd api && uv sync            # Hermes API deps

pnpm dev                     # Vite front-end only
pnpm tauri dev               # full desktop shell (needs Rust + WebKitGTK dev headers)
pnpm api                     # uvicorn on :8100 (from repo root)
cd api && uv run pytest      # event-schema round-trip test
```

## M1 bloom spike (run before building on Tauri — PRD §3.3)

```bash
cd desktop
SPIKE_RESULT_PATH=../docs/M1-spike-result.json SPIKE_AUTOEXIT=1 \
WEBKIT_FEATURES=UseGPUProcessForWebGL pnpm tauri dev
```

Renders 5k instanced glowing nodes + Bloom (HalfFloat), measures 600 frames
after warmup, writes the result JSON, and exits. Never set
`WEBKIT_DISABLE_DMABUF_RENDERER` / `WEBKIT_DISABLE_COMPOSITING_MODE` on this
AMD box (forces software render — PRD §3.5). Decision note: `docs/M1-*.md`.

## Non-negotiables (short form — full list PRD §3)

- Two independent single-GPU llama.cpp **Vulkan** workers; never tensor-split
  across cards, never vLLM TP≥2.
- GPU util/heat is **not** an activity signal (gfx1201 HIP idle bug) — real
  activity = streamed task/diff/log events.
- Embeddings local; vault content never leaves the box.
- Every capability is a Module (`docs/MODULE-CONTRACT.md`).
