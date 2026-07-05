# VAULT

**A terminal-first AI operating system for your homelab.** One keyboard-driven
TUI to run local LLMs across multiple GPUs, chat with per-card sessions, watch
your cloud orchestrator think in real time, execute and cancel streamed tasks,
mirror planned work to a kanban board, and pull any GGUF quant straight from
Hugging Face — all backed by a modular FastAPI event bus. Plus an optional
Tauri desktop HUD that renders your Obsidian vault as a glowing 3D knowledge
graph, because sometimes you want the Blade Runner wall display.

```
 VAULT · GPU DECK                                    local 6,239 tok · paid 0 tok
 ◉ AMD R9700 (gfx1201)      ██████████░░░░░░░░░░  21.9/34.2 GB
   ⚡ 25.3 tok/s · 1h Ø 31.2 tok/s · 44,731 tok
   ├─ [F1] vault-worker ● qwen3-coder-30b-a3b · 0 slot(s)
 ◉ NVIDIA GeForce RTX 4060 Ti  ████████░░░░░░░░  13.0/16.0 GB
   ⚡ 0.0 tok/s · 1h Ø 42.8 tok/s · 12,058 tok
   ├─ [F2] vault-worker ● gpt-oss-20b · 0 slot(s)

 CLOUD ORCHESTRATOR · ollama.com
   ├─ kimi-k2.6  4 req · in 89,292 / out 6,165 tok · 77.5 tok/s · 15958ms

 ASK SESSIONS
  ▸💬 help me design this schema ⠧  3 turns →r9700
   💬 summarize these notes         5 turns →4060ti

 RUNNING                             HISTORY
   idle                               ✓ M7.2 module refactor prep 12.7s
 ────────────────────────────────────────────────────────────────────────
 ORCHESTRATOR ⠋ thinking · kimi-k2.6 · 12s
 ›  type / for commands · bare text = ask the local model · /help
```

## What it does

- **Multi-GPU model serving** — independent llama.cpp (Vulkan) workers, one
  per card, each pinned to its GPU with its own port and OpenAI-compatible
  `/v1`. No tensor-splitting, no daemon in the middle, plain GGUF files.
- **Difficulty-based routing with paid fallback** — one endpoint
  (`POST /llm/complete`) routes `hard` work to your big card and `easy` work
  to the small one, falls through to any healthy lane, and escalates to the
  Anthropic API only when everything local is down — with a token ledger so
  you always know what a detour cost.
- **Chat sessions with memory, per GPU** — run parallel conversations, each
  pinned to a different card, switch between them from the deck, delete them
  when done. History rides along on every turn.
- **Cloud orchestrator observability** — a transparent local relay in front
  of ollama.com records exact tokens/latency per model for your cloud agent
  traffic, with a live "thinking" strip the moment a request is in flight.
- **Streamed task execution** — run shell commands server-side, watch stdout
  stream into the transcript, Esc to kill the whole process tree. Planned
  work (recognizable task ids) auto-mirrors to a Plane kanban board with
  live status; ad-hoc commands stay off the board.
- **Claude-Code-style drill-down** — arrow into any task: Miller columns,
  live transcripts, inline colored diffs, j/k scrolling, links to the board.
- **Any model from Hugging Face** — `/pull org/repo Q4_K_M` downloads into
  `~/llm-models/`; the catalog sniffs each GGUF's architecture and flags
  what your llama.cpp build can't load *before* you waste a load attempt.
- **An event bus everything speaks** — WebSocket + typed events (TS +
  Pydantic mirrors, round-trip tested). New capabilities are drop-in modules:
  a folder with a `register()` on the backend, an optional panel on the
  frontend, zero core changes.

## Architecture

```
┌─ vault (Textual TUI) ─────────┐   ┌─ Tauri HUD (optional) ──────────┐
│ deck · sessions · command line│   │ 3D vault graph · live panels    │
└──────────────┬────────────────┘   └──────────────┬──────────────────┘
               │  REST + WS (bearer, loopback)     │
        ┌──────┴───────────────────────────────────┴──────┐
        │        Hermes API (FastAPI, :8100)              │
        │  /graph /rag/query /notes /llm/complete /events │
        │  WS /ws/events · module registry + discovery    │
        └──┬──────────┬──────────┬──────────┬─────────────┘
     modules/: gpu-deck · task-runner · plane-sync · build-agent · grafana …
           │          │          │          │
   ┌───────┴──┐ ┌─────┴────┐ ┌───┴────┐ ┌───┴─────────────┐
   │ llama.cpp│ │ llama.cpp│ │ vault- │ │ cloud relay     │
   │ worker 1 │ │ worker 2 │ │ embed  │ │ :11500→ollama.com│
   │ GPU0:8081│ │ GPU1:8082│ │ :8084  │ │ (exact usage)   │
   └──────────┘ └──────────┘ └────────┘ └─────────────────┘
```

Everything runs on localhost with bearer-token auth. Vault content and
embeddings never leave the machine.

## Quickstart

Requirements: Linux, Python 3.11+ with [uv](https://docs.astral.sh/uv/),
Node 20+/pnpm (HUD only), a GPU with Vulkan drivers, and a
[llama.cpp](https://github.com/ggml-org/llama.cpp) release with the Vulkan
backend extracted somewhere (`LLAMA_DIR`, default `~/llm-workers/llama-<build>`).

```bash
git clone https://github.com/deresolution20/vault-os && cd vault-os
cp .env.example .env            # set VAULT_PATH, generate HERMES_API_TOKEN
cd api && uv sync && cd ..

# the API
cd api && uv run uvicorn vault_api.main:app --port 8100 &

# a worker (edit tools/run_worker_*.sh for your GPU names/ports/models)
cp tools/systemd/vault-worker-r9700.service ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user start vault-worker-r9700

# the TUI
ln -s "$PWD/tools/vault" ~/.local/bin/vault
vault
```

The worker launch scripts resolve GPUs **by device name** from
`llama-server --list-devices` and refuse to start into a VRAM squeeze —
adapt the name patterns and thresholds to your cards.

## Command reference

Type `/` in the prompt for the interactive palette (↑/↓ select, Tab/Enter
complete, live-filtered as you type). `/help` prints this list in-app.

### Talking to models

| Command | What it does |
|---|---|
| **bare text** (no slash) | Starts a **chat session** on the local model router. Routed by difficulty (`easy` → junior card), remembers the whole conversation, opens the session screen. |
| **`/ask <prompt>`** | Same as bare text — explicit form. |
| **`/ask <gpu> <prompt>`** | Pin the session to a specific card (e.g. `/ask r9700 design this schema`). Every turn goes to that card. If the pinned worker is down you get a clear error, never a silent detour. |
| **`/chats`** | Reopen the sessions screen on your latest conversation. Sessions also appear on the deck — arrow onto one and press Enter/→. |
| **`/clear-chats`** | Delete all chat sessions. `Ctrl+D` deletes just the selected one (works on the deck and inside a session). |
| **`/hermes <prompt>`** | One-shot to your cloud orchestrator agent with a **slim profile** (no memory/rules injection, minimal toolset — ~70% cheaper per call). |
| **`/hermes! <prompt>`** | Full-profile orchestrator call: memory, skills, all toolsets. Use for real agent work. |

### Managing models

| Command | What it does |
|---|---|
| **`/models`** | Catalog of local GGUFs: index, size, and the architecture read from each file's header. Models your llama.cpp build can't load are flagged `✗` with the reason. |
| **`/model <n>`** | Switch the default card's worker to catalog entry *n*. The worker restarts with the new model (~10–40s); the selection is **sticky** across restarts. |
| **`/model <gpu> <n\|name>`** | Same, targeting a specific card: `/model 4060ti 5`. Selecting for a not-yet-installed card persists the choice for when it arrives. |
| **`/pull <hf-repo> [quant]`** | Download a GGUF from Hugging Face into `~/llm-models/`. Without a quant it lists the repo's files (nothing downloads); with one (`Q4_K_M`) it fetches, with resume, progress streaming into the transcript. |

### Running things

| Command | What it does |
|---|---|
| **`/run <cmd>`** | Execute a shell command **server-side** in its own process group. stdout/stderr stream live into the transcript; a git diff of the working tree is captured on exit. |
| **`/cancel`** (or **Esc**) | Cancel the active task — kills the entire process tree, marks it `cancelled`. |
| **`/clear`** | Clear and hide the transcript pane. |

### Bookkeeping

| Command | What it does |
|---|---|
| **`/reset-cloud`** | Zero the cloud-orchestrator token window (records archived to `*.jsonl.1`, never destroyed). For clean measurement runs. |
| **`/reset-ledger`** | Zero the local/paid router token counters (previous values returned). |
| **`/help`** | Full command + key reference in the transcript. |
| **`/quit`** | Exit (also `Ctrl+Q`). |

### Keys

| Key | Context | Action |
|---|---|---|
| `↑` `↓` | deck | move the selection across sessions and tasks |
| `→` / `Enter` (empty prompt) | deck | open the selected session / drill into the selected task |
| `→` `→` then `j`/`k` | drill-down | focus the output pane, scroll it |
| `←` / `Esc` | drill-down | walk back out |
| `F1` `F2` `F3` | anywhere | **toggle** workers (stops a running one!) — every toggle is announced in the transcript |
| `Ctrl+D` | deck / session | delete the selected chat session |
| `Ctrl+O` | drill-down | open the task's Plane issue in your browser |
| `Esc` | layered | close palette → clear prompt → cancel task → hide transcript |

### Color identity

Every lane keeps one color everywhere — card headers, tok/s lines, session
pins, reply tags: **cyan** = GPU 1 (senior) · **green** = GPU 2 (junior) ·
**violet** = GPU 3 · **magenta** = cloud orchestrator · **red** = paid API
(if you see red, money moved).

## The event bus & modules

All activity — task lifecycles, log lines, diffs, vault-file changes, system
vitals — flows through `WS /ws/events` as typed events defined once in
`shared/events.ts` and mirrored in Pydantic (round-trip tested). A backend
module is a folder in `modules/` with a `module.py` exposing
`register(registry, bus)`; it can mount authed REST routes, emit events, and
declare a frontend panel. Drop the folder in, restart the API, done — the
`hello-module` in this repo is the three-line proof.

## The optional 3D HUD

`desktop/` is a Tauri v2 + React Three Fiber app that renders your Obsidian
vault as a force-directed, bloom-lit node cloud (notes = nodes, wikilinks =
edges, click to read), with the deck docked alongside. It hot-follows vault
edits via the same event bus. `pnpm install && pnpm tauri dev` — see
`docs/M1-decision-2026-07-03.md` for the GPU-pinning notes that made
WebKitGTK render it at 60fps.

## Provenance

Built as a pair-programming project between a human operator and Claude
(Anthropic), from PRD to production in a weekend — the commit history is the
build log. Research decisions (TUI framework, serving stack, render
architecture) were made via adversarially-verified deep research; the reports
live in `docs/`.

## License

[MIT](LICENSE)
