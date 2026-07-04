# PRD — VAULT: Voice-Activated Unified Logic Terminal (AI-OS, Step One)

**Owner:** Brice · **Author:** Claude + Brice · **Date:** 2026-07-03
**Build agent:** Fable 5 (via Hermes + Plane build-platform)
**Source of truth for tech choices:** `docs/RESEARCH-2026-07-03-vault-os-architecture.md` (deep-research report + verified ROCm/Tauri addendum). Every claim in this PRD traces back to that doc.

> **How to read this PRD (for the atomizer):** Each module lists discrete tasks. Every task has a **`[difficulty]`** tag — `trivial` / `easy` / `medium` / `hard` — used to route sub-coding work: `trivial`/`easy` → local GPU workers (token-saving), `hard` → the 32GB R9700 worker or paid-API fallback. Every task has an **acceptance criterion (AC)**. Tasks are ordered by dependency; the build order is in §9.

---

## 1. Vision & end state

A **desktop AI-OS** — a dark, cinematic HUD with a central **glowing, color-shifting, slowly-rotating 3D node cloud** that *is* my Obsidian vault (nodes = notes, edges = `[[wikilinks]]`), rendered Karpathy-style. Clicking a node opens its linked markdown. Around the graph, live panels show **what my local build-agents are actually doing right now** (task status, current diff, logs), plus system vitals. The whole thing exposes a **local API so my Hermes agent can read the graph, query the vault via RAG, write notes, and push live events** into the UI. It must be **modular** so I can later bolt on short-film video generation and ComfyUI image-gen as additional panels/workers.

**Step One (this PRD) = the unified dashboard + graph + RAG + Hermes API + live build telemetry + local model serving.** Video and ComfyUI modules are explicitly **out of scope** here (§10) but the architecture must accommodate them.

**Definition of done for Step One:** §8.

---

## 2. Recommended stack (verified)

| Layer | Choice | Why (see research doc) |
|---|---|---|
| Desktop shell | **Tauri** (Electron fallback ready) | Small footprint, Rust FS access to vault; AMD is the favorable WebKitGTK case — **gated by the bloom spike (M1)** |
| Front-end | **React + React Three Fiber + `r3f-forcegraph`** | Graph shares one canvas with HUD; native click callbacks |
| Bloom/glow | **`@react-three/postprocessing`** `<Bloom>` (HalfFloatType RTs) | Verified bloom path for R3F |
| Scale reserve | ~~cosmos.gl~~ — **not needed** (vault ~4k notes) | Would only apply above ~50k nodes; out of scope |
| Vault RAG | **`proofgeist/obsidian-notes-rag`** (sqlite-vec) + **local** embedding model | Local, no telemetry; ships MCP server. Local embeddings = fully offline |
| Vault write layer | **`obsidian-local-rest-api`** + **`cyanheads/obsidian-mcp-server`** (14-tool surface) | Verified read+WRITE MCP; STDIO or HTTP |
| Hermes API | **FastAPI** — REST + WebSocket (`send_json`) event bus | Verified WS pattern; fronts MCP + RAG |
| Model serving | **ROCm 7.2.x + llama.cpp Vulkan backend**, **two independent single-GPU workers** | RDNA4 needs ROCm 7; Vulkan avoids the HIP idle-power bug & beats vLLM-ROCm |
| Kanban / telemetry | **Plane** (API + webhooks) + **Grafana Cloud** (embed) | Existing infra |

---

## 3. Hard constraints (NON-NEGOTIABLE — from verified research)

1. **Model serving = ROCm 7.2.x, llama.cpp Vulkan backend, two independent processes** (one model per card, pinned via `HIP_VISIBLE_DEVICES`/Vulkan device index, each own port). **NEVER tensor-split one model across the two cards** — mismatched RDNA4+RDNA3 split is untested; even same-arch dual-GPU (vLLM TP=2) deadlocks. `[hard]`
2. **Do NOT infer "agent is working" from GPU util/heat.** The gfx1201 HIP idle-power bug pins util at 100% regardless of work; and Vulkan idles correctly. Real activity signal = **streamed task/diff/log events** (M6), not Grafana heat.
3. **Tauri is prototype-gated.** M1 (bloom spike on real AMD hardware) must pass before any further Tauri investment. If it fails → switch to Electron. Keep the front-end runtime-portable.
4. **Embeddings run locally** (e.g. `all-MiniLM-L6-v2` or better) — no cloud embedding provider. Vault content never leaves the box.
5. **On AMD, never set** `WEBKIT_DISABLE_DMABUF_RENDERER=1` / `WEBKIT_DISABLE_COMPOSITING_MODE=1` as defaults — they force software rendering and kill bloom. Crash-only fallbacks.
6. **Require WebKitGTK ≥ 2.48** (prefer 2.50/2.52); enable `UseGPUProcessForWebGL`.
7. **Detect software-render fallback empirically** (measure frame time with bloom active) — the WebGL renderer string is unreliable ("Apple GPU" on all Linux).
8. **Modularity is a day-one requirement**, not a later refactor: every capability is a Module implementing a uniform contract (§7 / M7).
9. **Workspace conventions apply** (root `CLAUDE.md`): durable artifacts in the repo (not scratchpad), secrets only in project `.env`, ask before anything that burns paid API credits or creates/publishes a repo.

---

## 4. Architecture overview

```
┌─────────────────────────── TAURI SHELL (Rust) ───────────────────────────┐
│  system tray · global hotkeys · vault FS watch · sidecar spawn            │
│  ┌───────────────────── React + R3F front-end ─────────────────────────┐ │
│  │  <Canvas>  r3f-forcegraph (nodes=notes, edges=wikilinks)             │ │
│  │            + <Bloom> postprocessing + color-shift + auto-rotate      │ │
│  │  HUD panels: Live Build · System Vitals · Documents · Command Deck   │ │
│  │            node click → open markdown (RAG-linked)                   │ │
│  └───────────────▲───────────────────────────────▲─────────────────────┘ │
└──────────────────│ WebSocket (events) ───────────│ REST (graph/RAG) ──────┘
                   │                                │
        ┌──────────┴────────────────────────────────┴──────────┐
        │            HERMES API  (FastAPI, localhost)            │
        │  GET /graph · POST /rag/query · POST|PATCH /notes      │
        │  WS /ws/events (send_json)   ·   Module registry       │
        └───┬───────────────┬───────────────┬───────────────────┘
            │               │               │
     ┌──────┴─────┐  ┌───────┴──────┐  ┌─────┴───────────────┐
     │ Vault index │  │ MCP write    │  │ Model router        │
     │ sqlite-vec  │  │ servers      │  │ (local-first,       │
     │ + graph gen │  │ (obsidian)   │  │  paid fallback)     │
     └─────────────┘  └──────────────┘  └───┬──────────┬──────┘
                                            │          │
                                   llama.cpp-Vulkan  llama.cpp-Vulkan
                                   R9700 32GB :8081   7900XTX 24GB :8082
```

---

## 5. Personas / actors

- **Brice (operator):** watches the HUD, clicks nodes, issues voice/command-deck intents.
- **Hermes (autonomous agent):** reads graph + RAG, writes notes, dispatches coding sub-tasks, emits live events. Primary API consumer.
- **Build sub-agents (local models):** the two GPU workers executing atomized coding tasks; emit status/diff/log events.

---

## 6. Modules & atomized tasks

### M0 — Foundation & scaffolding
**Objective:** monorepo, Tauri+React skeleton, shared event/type contracts, dev tooling.
- M0.1 `[easy]` Monorepo layout (`/desktop` Tauri+React, `/api` FastAPI, `/indexer`, `/modules`, `/shared` types). **AC:** `pnpm dev` + `uvicorn` both boot; README documents layout.
- M0.2 `[medium]` Tauri v2 shell: window, system tray, global hotkey (show/hide HUD), sidecar config to spawn the FastAPI backend. **AC:** tray icon toggles a fullscreen window; hotkey works; backend auto-spawns and is reachable.
- M0.3 `[easy]` Shared event schema (`shared/events.ts` + Pydantic mirror): `task_start`, `file_diff`, `log`, `task_done`, `node_update`, `system_vital`. **AC:** types compile both sides; one round-trip test passes.
- M0.4 `[trivial]` `.env.example`, config loader, `.gitignore` (vault path, keys, tokens). **AC:** app reads vault path + ports from env.

### M1 — Bloom spike (⚠️ GATING — decides Tauri vs Electron)
**Objective:** prove Three.js + UnrealBloom runs at framerate on the real AMD/WebKitGTK target BEFORE building on Tauri.
- M1.1 `[medium]` Minimal R3F scene: ~5k instanced glowing nodes + `<Bloom>` (HalfFloatType), fullscreen in the Tauri window on the real R9700/7900XTX box. **AC:** documented result.
- M1.2 `[easy]` Startup frame-time probe: measure ms/frame with bloom active; warn if below target (software-render detection). **AC:** logs measured FPS; flags software fallback.
- M1.3 `[easy]` **Decision gate & writeup:** confirm WebKitGTK ≥2.48 + `UseGPUProcessForWebGL`; record GO (Tauri) / NO-GO (Electron) in `docs/`. **AC:** dated decision note committed. **Blocks M3, M0.2 finalization.**

### M2 — Obsidian graph + RAG backend
**Objective:** one indexer that turns the vault into (a) graph JSON and (b) a local vector index; watches for changes.
- M2.1 `[medium]` Vault parser → `{nodes:[{id,path,title,tags}], links:[{source,target}]}` from markdown + `[[wikilinks]]` (incl. backlinks, unresolved links). **AC:** graph JSON matches Obsidian's own graph on a test vault (±edge-case notes).
- M2.2 `[medium]` Integrate `proofgeist/obsidian-notes-rag` (sqlite-vec) with a **local** embedding model; chunk notes by heading. **AC:** semantic query returns relevant notes; DB is a single local file; zero network calls verified.
- M2.3 `[medium]` File-watcher (Rust side or watchdog) → incremental re-index + emit `node_update` events on change. **AC:** editing a note updates graph + index within ~2s and pushes an event.
- M2.4 `[easy]` Expose indexer via internal calls for the API layer (graph getter, RAG query). **AC:** functions covered by unit tests.

### M3 — 3D graph visualization (the VAULT look)
**Objective:** the glowing, color-shifting, rotating clickable node cloud. **Depends on M1 GO + M2.1.**
- M3.1 `[medium]` `r3f-forcegraph` in shared `<Canvas>`, fed by `GET /graph`; node `filePath` attached. **AC:** vault renders as 3D force graph; pan/zoom/orbit works.
- M3.2 `[medium]` Glowing particle/shader node material via `nodeThreeObject`; selective bloom so nodes glow but panel text stays crisp (tune `luminanceThreshold`). **AC:** matches reference aesthetic on dark bg.
- M3.3 `[easy]` Color-shift-over-time (shader uniform driven by clock) + slow camera auto-orbit. **AC:** smooth hue cycle + rotation, no jank at target vault size.
- M3.4 `[easy]` `onNodeClick` → open linked markdown (Tauri command / MCP `open_file`) in a side panel with rendered markdown. **AC:** clicking a node shows its note content.
- M3.5 `[medium]` Perf pass: `cooldownTicks` freeze after layout, LOD/sprite fallback ≥ target node count; empirical FPS budget. **AC:** stays ≥ target FPS at documented vault size.
- ~~M3.6 cosmos.gl "huge vault" mode~~ — **CUT for Step One** (vault is ~4k notes; R3F handles this comfortably). Revisit only if the vault ever exceeds ~50k nodes.

### M4 — Hermes API layer
**Objective:** local REST + WebSocket API so Hermes reads graph, queries RAG, writes notes, and pushes live events.
- M4.1 `[medium]` FastAPI service: `GET /graph`, `POST /rag/query`, `POST /notes`, `PATCH /notes/{path}`. **AC:** OpenAPI docs; each endpoint integration-tested.
- M4.2 `[medium]` Wire write endpoints to `obsidian-local-rest-api` + `cyanheads/obsidian-mcp-server` (v4.0.0+, bearer auth, correct port). **AC:** Hermes creates + patches a note end-to-end; write is visible in Obsidian + reflected as a new/updated graph node.
- M4.3 `[medium]` `WS /ws/events` with `send_json`; connection manager fans events to all clients. **AC:** front-end subscribes; emitted event appears in a panel < 500ms.
- M4.4 `[easy]` Auth (local bearer token) + bind to localhost only. **AC:** unauthenticated request rejected; not exposed off-box.

### M5 — Local model serving (ROCm 7 + Vulkan, two workers)
**Objective:** two independent OpenAI-compatible local endpoints + a router that farms coding sub-tasks, local-first with paid fallback.
- M5.1 `[hard]` Provision ROCm 7.2.x on Ubuntu 24.04.x; build/run `llama-server` **Vulkan** backend on **each** card, pinned + own port (R9700→large coding model, 7900XTX→fast model). **AC:** both `/v1` endpoints serve completions; cards idle correctly at rest (Vulkan). *(Coordinate with `projects/r9700-kernel` work.)*
- M5.2 `[medium]` Model router (part of Hermes): route by task difficulty tag → R9700 (hard/long-context) vs 7900XTX (cheap/parallel); health checks. **AC:** dispatcher balances two lanes; picks correct card by tag.
- M5.3 `[medium]` **Local-first, paid-API fallback:** on local error/timeout/over-capacity, escalate to paid API; log token savings. **AC:** kill a local worker → request completes via fallback; savings metric emitted.
- M5.4 `[easy]` *(optional)* vLLM-ROCm TP=1 recipe for R9700 only (FP8, `VLLM_ROCM_USE_AITER=0`) documented as an alternative. **AC:** doc + smoke test. **Never TP≥2.**

### M6 — Live build-agent telemetry + Plane/Grafana
**Objective:** surface "what are the models building right now" and connect the board.
- M6.1 `[medium]` Build sub-agents emit `task_start/file_diff/log/task_done` to Hermes; "Live Build" panel renders current task + streaming diff + tail logs. **AC:** running a real sub-task shows live diff/log in the HUD.
- M6.2 `[medium]` Plane integration: outbound (create/update issue on task start/finish) + inbound webhook (moving a card triggers a Hermes task). **AC:** agent work mirrored on the board; card move kicks a task.
- M6.3 `[easy]` Embed Grafana Cloud GPU panels (VRAM/temp/util) in a System Vitals panel via signed embed/iframe. **AC:** panels render in-app. **Label them "resource" not "activity"** (see constraint #2).
- M6.4 `[easy]` System vitals strip (subscriber counts / clock / directives style from reference) fed by config + events. **AC:** matches reference layout.

### M7 — Modular plugin architecture
**Objective:** uniform Module contract so future video/ComfyUI slot in without touching core.
- M7.1 `[medium]` Define Module contract: a module registers (a) REST routes, (b) WS event types, (c) optional dashboard panel component. Core discovers + mounts. **AC:** documented interface + one loaded example.
- M7.2 `[medium]` Refactor RAG, write-layer, model-serving, telemetry as registered modules through the contract. **AC:** each mounts via registry; removing one doesn't break others.
- M7.3 `[easy]` **Stub module** ("hello-module": one route, one event, one panel) proving a new capability is drop-in. **AC:** stub appears in UI + emits an event with no core changes. *(This is the modularity proof for later ComfyUI/video.)*

---

## 7. Cross-cutting requirements

- **Aesthetic:** dark HUD, monospace/terminal type, amber/gold accents matching the reference; graph is the centerpiece.
- **Graph as hub:** module outputs can write notes back to the vault (M4.2) → appear as new nodes → closes the generation↔knowledge loop.
- **Everything speaks HTTP + the shared WS event bus**; local models speak OpenAI-compatible API (so future ComfyUI/video workers reuse the M5 dispatcher and M6 event stream).
- **Observability:** structured logs; token-savings + fallback counters exported to Grafana.

---

## 8. Definition of Done (Step One)

1. Tauri (or Electron per M1) HUD launches fullscreen with tray + hotkey.
2. Central 3D graph renders the real vault — glowing, color-shifting, rotating; clicking a node opens its markdown.
3. `GET /graph`, `POST /rag/query`, note create/patch all work; a write shows up as a new graph node.
4. `WS /ws/events` streams live; the "Live Build" panel shows a real sub-agent's task + diff + logs.
5. Two local llama.cpp-Vulkan workers serve on ROCm 7; router farms by difficulty; paid fallback proven.
6. Plane mirrors agent work; Grafana GPU panels embedded (labeled "resource").
7. Module contract exists; the stub module proves drop-in extensibility.
8. All hard constraints (§3) satisfied; research doc + decision notes committed under `docs/`.

---

## 9. Build order (dependency-aware)

1. **M0** foundation → 2. **M1 bloom spike (GATE)** → 3. **M2** backend + **M5.1** serving (parallelizable) → 4. **M4** API → 5. **M3** visualization → 6. **M6** telemetry + **M5.2/5.3** router → 7. **M7** modularize + stub.

Rationale: M1 de-risks the whole front-end before investment; M2/M5.1 are independent infra that can build in parallel on the two GPUs; M7 comes last but its contract (M7.1) should be sketched during M0.

---

## 10. Out of scope (Step One) — but architecture must accommodate

- Short-film **video generation** module.
- **ComfyUI** dual-card image-gen module.
- Voice I/O / TTS (reference shows "AUDIO I/O · TTS.STANDBY") — stub the panel, defer implementation.
- Multi-user / remote access (localhost-only for now).

These arrive later as **M7 modules** reusing the event bus + model dispatcher.

---

## 11. Decisions (RESOLVED 2026-07-03)

| # | Question | **Decision** |
|---|---|---|
| 1 | Vault size / M3 vs cosmos.gl path | **~4k notes → R3F only.** cosmos.gl NOT needed for Step One; M3.6 cut (see below). No scale risk. |
| 2 | Canonical MCP write server | **`obsidian-local-rest-api` + `cyanheads/obsidian-mcp-server`** (14-tool surface, STDIO/HTTP). |
| 3 | Node color meaning vs aesthetic | **Pure aesthetic time-cycle now**, with data-driven hooks stubbed (recency/cluster/agent-activity later). |
| 4 | Live-diff source | **Git diff of the sub-agent's working tree.** |
| 5 | Local models per card | **R9700 32GB → larger coding model (30B-class MoE / 14B long-context). 7900XTX 24GB → fast 7–14B.** |
| 6 | Indexer language | **Python (FastAPI) sidecar**; Rust only for the FS watcher. |
| 7 | Selective bloom fidelity | **Yes — selective bloom, nodes glow, panels/text excluded.** |

*All defaults accepted except #1, which is now pinned to the real ~4k-note vault size.*
