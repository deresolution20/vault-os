# VAULT Step One — atomized backlog (Plane-ready)

**Status:** MIRRORED to Plane 2026-07-03 (workspace `build-platform`,
project id `72e8c59a-4773-44c0-9ea6-886138a2241d`, http://localhost:30080).
This file remains the canonical state ledger; re-sync with
`tools/push_backlog_to_plane.py` (idempotent — only creates missing issues;
state changes here are not yet pushed back, update Plane manually or extend
the tool).

Labels to carry onto each issue: `difficulty:<tag>`, `module:<M#>`.
**Build agent: Fable 5 builds ALL tasks directly (Brice's directive 2026-07-03
— do NOT farm coding tasks to local models).** The difficulty tags are kept as
effort metadata and for the M5 *runtime* router (an app feature for Hermes's
own inference, not a build workforce).

| ID | Title | Difficulty | State | Depends on | Notes |
|---|---|---|---|---|---|
| M0.1 | Monorepo layout (desktop/api/indexer/modules/shared) | easy | **done 2026-07-03** | — | scaffolded; README documents layout |
| M0.2 | Tauri v2 shell: tray, global hotkey, sidecar spawn | medium | **done 2026-07-03** — tray toggle/quit, ctrl+shift+v, sidecar spawn/reap, AMD GL pin | M1.3 | hotkey delivery on Wayland pending Brice keypress check |
| M0.3 | Shared event schema TS + Pydantic + round-trip test | easy | **done 2026-07-03** | — | fixtures test green both sides |
| M0.4 | .env.example, config loader, .gitignore | trivial | **done 2026-07-03** | — | pydantic-settings reads project .env |
| M1.1 | Bloom spike scene (5k instanced nodes + Bloom) on real box | medium | **done 2026-07-03** — 60fps vsync @4K on R9700 | M0.1 | `desktop/src/spike/` |
| M1.2 | Startup frame-time probe + software-render flag | easy | **done 2026-07-03** — correctly flagged the NVIDIA software path | M1.1 | writes `docs/M1-spike-result.json` |
| M1.3 | Decision gate writeup: GO (Tauri) / NO-GO (Electron) | easy | **done 2026-07-03 — GO (Tauri)** | M1.1, M1.2 | `docs/M1-decision-2026-07-03.md`; launcher must pin AMD GL |
| M2.1 | Vault parser → graph JSON (wikilinks, backlinks, unresolved) | medium | **done 2026-07-03** — 5 tests green, ghost nodes + stem resolution | — | |
| M2.2 | obsidian-notes-rag + local embeddings, chunk by heading | medium | **done 2026-07-03** — local ollama nomic-embed-text, sqlite-vec, heading chunks | — | zero-network verify |
| M2.3 | File-watcher → incremental re-index + node_update events | medium | **done 2026-07-03** — watchdog → reindex + node_update <2s (e2e test) | M2.1 | |
| M2.4 | Indexer exposed to API layer + unit tests | easy | **done 2026-07-03** — build_graph + RagService behind API, tests green | M2.1, M2.2 | |
| M3.1 | r3f-forcegraph in shared Canvas fed by GET /graph | medium | **done 2026-07-03** — r3f-forcegraph fed by GET /graph, orbit works | M1.3 GO, M2.1 | |
| M3.2 | Glow node material + selective bloom | medium | **done 2026-07-03** — additive glow sprites + bloom, DOM panels crisp | M3.1 | |
| M3.3 | Color-shift over time + slow auto-orbit | easy | **done 2026-07-03** — Blade Runner palette breathe + slow auto-orbit | M3.1 | spike already proves the technique |
| M3.4 | Node click → markdown side panel | easy | code done — awaiting Brice click-test (read_note sandboxed to vault) | M3.1 | |
| M3.5 | Perf pass (cooldownTicks freeze, LOD, FPS budget) | medium | **done for current scale** — cooldownTicks freeze + startup FPS canary (60fps); 5k case proven by M1 | M3.1–M3.4 | |
| M4.1 | FastAPI: GET /graph, POST /rag/query, POST/PATCH /notes | medium | **done 2026-07-03** — /graph, /rag/query, /notes, PATCH /notes/{path} | M2.4 | skeleton app exists |
| M4.2 | Wire writes to obsidian-local-rest-api + cyanheads MCP | medium | **done 2026-07-03** — create+PATCH e2e via HTTPS 27124; write → watcher → graph node verified | M4.1 | plugin 4.1.3 installed (Brice-approved), key in .env |
| M4.3 | WS /ws/events + connection manager fan-out | medium | **done 2026-07-03** — WS bus fan-out, e2e <500ms in watcher test | M0.3 | `bus.py` |
| M4.4 | Bearer auth + localhost-only bind | easy | **done 2026-07-03** — bearer auth REST+WS, loopback bind, /health open | M4.1 | |
| M5.1 | ROCm 7.2.x + llama-server Vulkan on R9700 (worker 1) | hard | **done 2026-07-04** — llama.cpp b9870 Vulkan, qwen3-32B q4, 25 tok/s, idles correctly (no HIP pin); worker start-on-demand | — | coordinate `projects/r9700-kernel` |
| M5.1b | Second Vulkan worker on 7900 XTX | hard | **waits for card (~Jul 7)** | M5.1 | |
| M5.2 | Model router: route by difficulty tag + health checks | medium | **done (single-lane live) 2026-07-04** — hard→r9700 verified via /llm/complete; dual-lane balancing waits for 7900 XTX | M5.1 | full balancing needs both cards |
| M5.3 | Local-first paid-API fallback + savings metric | medium | **code done 2026-07-04** — fallback + token ledger, mocked; real paid call awaits Brice approval | M5.2 | ⚠ burns paid credits — confirm with Brice before load-testing |
| M5.4 | (opt) vLLM-ROCm TP=1 recipe doc, R9700 only | easy | todo | M5.1 | never TP≥2 |
| M6.1 | Sub-agents emit task/diff/log events → Live Build panel | medium | **done 2026-07-04** — POST /events + emit_build_events.py + Live Build panel; demo verified | M4.3 | |
| M6.2 | Plane outbound issues + inbound webhook | medium | **done 2026-07-04** — task_start→RUN issue→completed live-verified; inbound webhook re-emits (dispatcher = Hermes wiring later) | M4.1 | push tool ready: `tools/push_backlog_to_plane.py` |
| M6.3 | Grafana embed in System Vitals ("resource", not activity) | easy | **done (code) 2026-07-04** — module + iframe panel; needs GRAFANA_EMBED_URL from Brice to render | — | needs GRAFANA_EMBED_URL |
| M6.4 | System vitals strip | easy | **done 2026-07-04** — vitals loop → HUD strip, labeled resource-not-activity | M4.3 | |
| M7.1 | Module contract defined + one loaded example | medium | **done 2026-07-04** — contract + filesystem discovery + 4 loaded modules | — | example module = M7.3 |
| M7.2 | Refactor RAG/write/serving/telemetry as modules | medium | todo | M7.1, M4, M5, M6 | |
| M7.3 | hello-module stub (route + event + panel, drop-in proof) | easy | **done 2026-07-04** — hello-module: route+event+panel, zero core edits, tested | M7.1 | |
