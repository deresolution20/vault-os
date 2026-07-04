# VAULT — Step One build brief (for Fable 5)

*Paste everything below the line as the `/goal` input.*

---

## GOAL

Build **Step One of VAULT** — a Tauri desktop AI-OS. A dark HUD whose centerpiece is a glowing, color-shifting, slowly-rotating **3D node cloud of my Obsidian vault** (nodes = notes, edges = `[[wikilinks]]`; click a node → its markdown opens). Around it, live panels show **what my local build-agents are doing right now**. It's backed by a local **Hermes API** (REST + WebSocket) and **two local AMD GPU model workers**, and is **modular** so I can add video/ComfyUI later.

## READ FIRST (source of truth — do not re-derive)

1. `projects/vault-os/docs/PRD-vault-os.md` — the 7 modules, atomized tasks, `[difficulty]` tags, acceptance criteria, dependency-ordered build plan (§9), definition of done (§8). All 7 design decisions are already resolved (§11).
2. `projects/vault-os/docs/RESEARCH-2026-07-03-vault-os-architecture.md` — verified research behind every tech choice, incl. the ROCm/RDNA4 + Tauri addendum. Choices here are settled; if you want to diverge, raise it with me first.

## YOUR ROLE (WAT framework — see root `CLAUDE.md`)

You are the orchestrator. Atomize the PRD into **Plane issues, one per task** (M0.1, M1.1, …), carrying each `[difficulty]` tag onto the issue. Route by tag to save tokens: `trivial`/`easy` → local GPU workers; `hard` → the R9700 worker or paid-API fallback. Build in PRD dependency order. Prefer existing tools; write deterministic scripts for anything repeated. Recover from failures and fold the lesson back into the workflow.

## HARD GUARDRAILS — do not violate (verified; PRD §3)

1. **M1 bloom spike is a GATE.** Prove Three.js + UnrealBloom runs at framerate on the real AMD/WebKitGTK box *before* building further on Tauri. If it fails → Electron. Keep the front-end runtime-portable either way.
2. **Serving = ROCm 7.2.x + llama.cpp Vulkan backend, TWO independent single-GPU workers** (one model/card, pinned, own port). **NEVER tensor-split one model across the two cards. NEVER vLLM TP ≥ 2.**
3. **GPU util/heat is NOT an activity signal** (gfx1201 HIP idle-power bug pins it at 100%). Real activity = streamed task/diff/log events only.
4. **Embeddings run locally; vault content never leaves the box.** No cloud embedding provider.
5. On AMD, do **not** default to `WEBKIT_DISABLE_DMABUF_RENDERER` / `WEBKIT_DISABLE_COMPOSITING_MODE` (they force software render, killing bloom). Require WebKitGTK ≥ 2.48 + `UseGPUProcessForWebGL`.
6. **Modularity is day-one:** every capability is a Module (route + events + optional panel) so video/ComfyUI slot in later without touching core.

## STOP AND ASK ME BEFORE

- Anything that **burns paid API credits at scale** or changes the local↔paid fallback economics.
- **Creating or publishing any git repo, or making one public** — default private, confirm visibility with me first.
- **Overwriting/deleting** existing workflows, tools, or the GPU workers' serving config.
- **Diverging** from a settled PRD tech choice.

## CONVENTIONS

Durable artifacts → the repo (never scratchpad). Secrets → project `.env` only. ROCm/serving work coordinates with `projects/r9700-kernel`. Write a `/handoff` before any context/account limit.

## DEFINITION OF DONE

PRD §8 (all 8 criteria). When met and committed, report back with a demo path: **launch → 3D vault graph → click a node → live build panel updating → both GPU workers serving.**

## START HERE

1. Scaffold **M0** (monorepo, Tauri+React skeleton, shared event schema, config).
2. Sketch the **M7 module contract** (so everything after is built as a module).
3. Run the **M1 bloom spike** and report **GO (Tauri) / NO-GO (Electron)** before building M3.

**Hardware note — sequence M5 accordingly:** only the **R9700 (32GB) is installed now**; the **7900 XTX (24GB) arrives ~week of Jul 7**. Everything through M0→M1→M2→M4→M3 needs no second AMD card — do that now. **M5.1** can provision the *single* R9700 Vulkan worker now; the **second worker + router balancing (M5.2/M5.3) wait for the 7900 XTX**. Don't block earlier modules on the missing card.

*(All §11 decisions are pinned — vault is ~4k notes → R3F only, no cosmos.gl. No need to re-confirm scope.)*
