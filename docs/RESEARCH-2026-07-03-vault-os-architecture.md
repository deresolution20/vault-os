# VAULT AI-OS: A Deep Technical Research Report on Building a Voice-Activated Unified Logic Terminal

## Executive summary

Building the "VAULT" dashboard — a dark HUD with a central glowing, color-shifting, rotating 3D knowledge graph of your Obsidian vault, surrounded by live agent panels — is very achievable in 2026 with mature, well-documented open-source components. For the **visualization**, the fastest path to the exact Karpathy-style bloom aesthetic is Vasturiano's `3d-force-graph` (or its React-Three-Fiber binding `r3f-forcegraph`), because it renders force-directed graphs in Three.js/WebGL, exposes the post-processing composer for UnrealBloom glow, allows fully custom particle/glow node materials, and gives you `onNodeClick` to open the linked markdown note; for vaults far beyond 10k nodes, GPU-in-shader engines like **cosmos.gl** (the engine behind Cosmograph) scale to hundreds of thousands of nodes. For the **backend**, an Obsidian vault becomes both a graph and a RAG index by parsing `[[wikilinks]]` into nodes/edges and embedding markdown chunks into a local vector store (sqlite-vec, LanceDB, Chroma, or Qdrant), and there is a rich ecosystem of ready-made MCP servers (`obsidian-local-rest-api`, `cyanheads/obsidian-mcp-server`, `MarkusPfundstein/mcp-obsidian`, `aaronsb/obsidian-mcp-plugin`) that already expose read **and write** access. For the **Hermes agent API**, wrap those MCP servers plus a FastAPI service that exposes REST for queries and a WebSocket (`@app.websocket`, `send_json`) channel to push live status to the dashboard. The recommended end-to-end stack: **Tauri desktop shell → R3F/`r3f-forcegraph` + `@react-three/postprocessing` Bloom front-end → FastAPI + MCP backend → local vector store → llama.cpp/vLLM on ROCm across your two AMD cards**. Note upfront: the verified research material is deep on visualization and Obsidian/MCP tooling, but **thin on the Tauri-vs-Electron, AMD/ROCm, and Plane/Grafana specifics** — those sections below lean on general engineering knowledge and are explicitly flagged as not drawn from the verified claim set, so treat them as directional and re-verify before committing hardware or build decisions.

---

## 1. 3D graph visualization

This is the best-supported area in the verified material, and the recommendation is clear.

### Library choice

**Primary recommendation: `3d-force-graph` / `r3f-forcegraph` (Vasturiano family).** The core library `3d-force-graph` "represent[s] a graph data structure in a 3-dimensional space using a force-directed iterative layout" and "uses ThreeJS/WebGL for 3D rendering" ([github.com/vasturiano/3d-force-graph](https://github.com/vasturiano/3d-force-graph)). It directly exposes the two interaction hooks you need — `onNodeClick(node, event)` and `onNodeHover(node, prevNode)` — with the full node object passed to the callback, so you can attach an Obsidian file path to each node and open it on click ([github.com/vasturiano/3d-force-graph](https://github.com/vasturiano/3d-force-graph)).

If your dashboard is a React app (recommended for the panel layout), use **`r3f-forcegraph`**, which provides "React-Three-Fiber bindings for the three-forcegraph ThreeJS component" and renders as a native `<R3fForceGraph>` component **inside your own `<Canvas>`** rather than as a standalone canvas ([github.com/vasturiano/r3f-forcegraph](https://github.com/vasturiano/r3f-forcegraph)). This matters: it lets the graph share one Three.js scene with your other HUD 3D elements, lights, and post-processing stack, which is exactly what you want for a unified bloom-lit look. It exposes the same click callbacks — `onNodeClick`, `onLinkClick` — for wiring node selection to opening a note ([github.com/vasturiano/r3f-forcegraph](https://github.com/vasturiano/r3f-forcegraph)).

**Scale alternative: `cosmos.gl` (Cosmograph engine).** If your vault is genuinely huge (tens to hundreds of thousands of notes/links), consider `cosmos.gl`, a WebGL2 engine where "all the computations and drawing occur on the GPU in fragment and vertex shaders, avoiding expensive memory operations" ([github.com/cosmosgl/graph](https://github.com/cosmosgl/graph)). It can do "real-time simulation of network graphs consisting of hundreds of thousands of points and links on modern hardware" ([github.com/cosmosgl/graph](https://github.com/cosmosgl/graph)) — comfortably exceeding the 1k–10k target. The tradeoff: cosmos.gl runs *layout* on the GPU and is a 2D-first engine optimized for scale; it does not give you the same easy per-node custom Three.js geometry or the 3D rotating-cloud aesthetic out of the box. **For the VAULT look at 1k–10k nodes, prefer the Three.js/R3F route; keep cosmos.gl in reserve as a "huge vault" module.**

The other libraries named in your brief (Sigma.js, deck.gl, plain Three.js) are viable but sit at the extremes: Sigma.js is 2D/WebGL and graph-specialized but not the 3D glowing cloud you want; deck.gl is a GPU layer-rendering framework better suited to geospatial/large-scatter data than force-directed knowledge graphs; raw Three.js + R3F gives maximal control but means re-implementing the force layout that `three-forcegraph` already provides. The verified material did not surface specific claims on Sigma.js or deck.gl, so treat comparisons to them as general knowledge rather than verified fact.

### Bloom / glow (the "bloom-lit" aesthetic)

Two concrete paths, both verified:

1. **Imperative (`3d-force-graph`):** The library exposes `postProcessingComposer()`, which returns the internal Three.js `EffectComposer`, so you add an `UnrealBloomPass`: `Graph.postProcessingComposer().addPass(bloomPass)`. The repo ships an official bloom-effect example and multiple issues (#201, #265, #321, #421) demonstrate exactly this pattern ([github.com/vasturiano/3d-force-graph](https://github.com/vasturiano/3d-force-graph)).

2. **Declarative (R3F):** Use `@react-three/postprocessing` (`react-postprocessing`), which "provides a Bloom effect for react-three-fiber." Minimal usage is `<EffectComposer><Bloom luminanceThreshold={0} luminanceSmoothing={0.9} height={300} /></EffectComposer>` inside your `<Canvas>` ([github.com/pmndrs/react-postprocessing](https://github.com/pmndrs/react-postprocessing)). This is the cleaner option when you're already using `r3f-forcegraph` in a shared canvas.

To make bloom "pop" selectively (glowing nodes on a dark HUD without washing out text panels), set node materials to emissive/high-luminance and tune `luminanceThreshold` so only the bright nodes bloom — the standard selective-bloom technique.

### Particle / glow node materials

Both the core and R3F libraries let you replace the default sphere with arbitrary Three.js objects via **`nodeThreeObject()`**, which "should return an instance of ThreeJS Object3d" ([github.com/vasturiano/3d-force-graph](https://github.com/vasturiano/3d-force-graph); [github.com/vasturiano/r3f-forcegraph](https://github.com/vasturiano/r3f-forcegraph)). Because `THREE.Object3D` is the base class for `Mesh`, `Points` (particle systems), and `Sprite`, you can return glowing `Points` clouds, additive-blended sprites, or custom shader-material meshes per node — this is the mechanism for the "Karpathy-style glowing particle nodes." The companion `nodeThreeObjectExtend` flag controls whether your object replaces or augments the default sphere.

### Color-shift-over-time animation and auto-rotation

The verified material did **not** contain specific claims on time-based color animation or auto-rotation APIs, so here is honest general guidance (not from the claim set):

- **Color shift:** Drive node/material color from a clock. In R3F, use a `useFrame((state) => …)` loop to animate an HSL hue offset (`color.setHSL((t * speed) % 1, s, l)`) across node materials, or feed `state.clock.elapsedTime` into a custom shader uniform for a smooth palette cycle. In the imperative library, run your own `requestAnimationFrame` loop mutating material colors.
- **Auto-rotation:** Slowly rotate the camera (orbit) rather than the graph itself for a stable HUD feel — e.g., increment the camera's azimuthal angle each frame, or use drei's `OrbitControls autoRotate` in R3F. `3d-force-graph` also has a camera-orbit pattern in its examples. Re-verify exact method names against current docs.

### Performance at 1k–10k+ nodes

- `3d-force-graph`/`r3f-forcegraph` (Three.js/WebGL) comfortably handle 1k–10k nodes; beyond that, layout on the CPU becomes the bottleneck, and you should (a) freeze the simulation after initial layout (`cooldownTicks`), (b) use cheaper node objects (sprites/points instead of high-poly meshes), and (c) consider level-of-detail. These are general Three.js practices, not verified claims.
- For 10k → 100k+, switch to the GPU-in-shader model of `cosmos.gl`, which stays fluid at "hundreds of thousands of nodes" after its v3 luma.gl/WebGL2 migration ([github.com/cosmosgl/graph](https://github.com/cosmosgl/graph)).

### Node click → open linked markdown

Wire `onNodeClick(node)` → read `node.filePath` (or `node.path`, whatever you set when building the graph) → invoke your desktop shell's "open file" IPC (Tauri command / Electron IPC) or hit the Obsidian Local REST API `open_file` tool to focus the note in Obsidian. Both `3d-force-graph` and `r3f-forcegraph` pass the full node object to the callback, making this trivial ([github.com/vasturiano/3d-force-graph](https://github.com/vasturiano/3d-force-graph); [github.com/vasturiano/r3f-forcegraph](https://github.com/vasturiano/r3f-forcegraph)).

---

## 2. Obsidian graph + RAG backend

Your vault needs to become two artifacts from one source of truth: **(a)** a `{nodes, links}` graph for the visualization, and **(b)** a vector index for RAG. The good news is that both can be derived from the same markdown + wikilink corpus, and several existing tools do most of the work.

### Wikilink → nodes/edges

The node/link data structure is a direct parse of the vault: each markdown file is a node; each `[[wikilink]]` (and its backlink) is an edge. You can build this yourself (walk the vault, regex/parse `[[...]]`, resolve to file paths, emit `{nodes:[{id, path, title}], links:[{source, target}]}`), or lean on MCP servers that already expose graph traversal:

- `aaronsb/obsidian-mcp-plugin` provides dedicated **graph-traversal tools** — "traverse, find paths, analyze connections" — with "multi-hop traversal with depth control," "backlink and forward-link analysis," and "path finding between concepts" ([github.com/aaronsb/obsidian-mcp-plugin](https://github.com/aaronsb/obsidian-mcp-plugin)). This lets an agent navigate the wikilink structure and can supply graph data for both the visualization and RAG context.

### Embeddings + local vector stores

Chunk each note (by heading/paragraph), embed the chunks with a local model, and store vectors locally. Verified concrete options:

- **`proofgeist/obsidian-notes-rag`** stores vectors locally in **sqlite-vec** (via `vec0` virtual tables for KNN search), with metadata in SQLite, "~200KB, no telemetry, no network calls"; **v1.0.0 replaced ChromaDB with sqlite-vec** ([github.com/proofgeist/obsidian-notes-rag](https://github.com/proofgeist/obsidian-notes-rag)). It also **ships an MCP server** (via `obsidian-notes-rag serve`) exposing `search_notes` (semantic search), `get_similar` (related content), and `get_note_context` to any MCP-compatible assistant ([github.com/proofgeist/obsidian-notes-rag](https://github.com/proofgeist/obsidian-notes-rag)). This is arguably the single best "drop-in RAG index for an Obsidian vault" in the verified set. *(Caveat: the "no network calls" property applies to the storage layer; choosing OpenAI as the embedding provider does make network calls — use a local embedding model to stay fully offline.)*
- **`local-rest-api-second-brain-mcp-extension`** combines **local-embedding semantic search** (models "like `all-MiniLM-L6-v2`") with **breadth-first traversal of Obsidian's internal link graph** across both outgoing links and backlinks to retrieve contextually related notes ([community.obsidian.md/plugins/local-rest-api-second-brain-mcp-extension](https://community.obsidian.md/plugins/local-rest-api-second-brain-mcp-extension)). This is a nice hybrid: vector search picks entry-point ("root") notes, then graph BFS expands context — well-suited to a linked knowledge base. It exposes an MCP endpoint at `/second-brain-mcp/` and, importantly, **layers on the Obsidian Local REST API plugin, reusing its auth and web server** rather than running its own ([community.obsidian.md/plugins/local-rest-api-second-brain-mcp-extension](https://community.obsidian.md/plugins/local-rest-api-second-brain-mcp-extension)).

On the specific stores you named — **LanceDB, Chroma, Qdrant** — the verified material only concretely covers **sqlite-vec** (via `obsidian-notes-rag`) and notes that Chroma was *replaced* by sqlite-vec in that project. So: sqlite-vec is the verified lightweight embedded default; LanceDB (embedded, columnar, good for larger corpora), Chroma (simple local server), and Qdrant (production-grade, filtering, hybrid search) are all reasonable per general knowledge, but the material did not surface verified claims about them for this use case. If you want zero-ops and a single file, **sqlite-vec**; if you expect the vault to grow large or want richer filtering, **Qdrant** or **LanceDB** are the conventional step-ups (treat that as directional, not verified).

### Existing tools (Smart Connections, khoj, basic-memory, obsidian-mcp servers)

The verified material strongly covers the **MCP-server** ecosystem (see §3) and `obsidian-notes-rag`, but did **not** surface specific verified claims about Smart Connections, khoj, or basic-memory. Those are real, well-known projects — Smart Connections (in-Obsidian semantic search/embeddings), khoj (self-hosted AI second-brain with Obsidian support), basic-memory (MCP-based markdown knowledge store) — but I'm flagging them as **not verified here**; check their current docs directly before depending on them.

**Recommended backend shape:** one indexer process that (1) watches the vault, (2) rebuilds the `{nodes, links}` graph JSON for the front-end, and (3) chunks+embeds notes into sqlite-vec via `obsidian-notes-rag`. Expose both through the Hermes API in §3.

---

## 3. Agent (Hermes) API layer

Hermes needs to **read the graph, query RAG, and write markdown notes**, plus **push live status** to the dashboard. The verified material gives you a full menu of write-capable MCP servers plus the FastAPI WebSocket primitives.

### The write layer — pick an MCP server (all verified read + WRITE)

You have four strong, verified options. All bridge to or embed inside Obsidian and support create/edit of markdown:

| Server | Transport | Write capabilities | Connection model |
|---|---|---|---|
| **`obsidian-local-rest-api`** (coddingtonbear) | HTTPS REST (self-signed cert, bearer token) + built-in MCP at `/mcp/` (Streamable HTTP) | Full CRUD on any vault file + surgical PATCH to headings/blocks/frontmatter | Runs inside Obsidian; ports 27124 (HTTPS) / 27123 (HTTP) |
| **`cyanheads/obsidian-mcp-server`** | STDIO **or** Streamable HTTP (`MCP_TRANSPORT_TYPE`) | 14 tools incl. `obsidian_write_note`, `obsidian_append_to_note`, `obsidian_patch_note`, `obsidian_replace_in_note`, `obsidian_delete_note` | **Wraps** Local REST API plugin (v4.0.0+), default `http://127.0.0.1:27123` |
| **`MarkusPfundstein/mcp-obsidian`** | MCP (via Local REST API) | `append_content`, `patch_content` (relative to heading/block/frontmatter), `delete_file` | Bridges to Local REST API plugin, default `127.0.0.1:27124` |
| **`aaronsb/obsidian-mcp-plugin`** | Own embedded HTTP (3001) / HTTPS (3443) MCP server, bearer auth | list, read, create, search, move, split, combine + window editing, append, patch sections | Runs **inside** Obsidian, no Local REST API dependency |

Details and sources:

- **`obsidian-local-rest-api`** gives "full CRUD (create, update, read, delete) on any file in your vault," over HTTPS with bearer-token auth, and now ships a **built-in MCP server at `/mcp/` using Streamable HTTP transport** with tools for vault operations, file patching, search, tags, and command execution — so an MCP-native agent connects with just an `Authorization: Bearer` header, no separate bridge ([github.com/coddingtonbear/obsidian-local-rest-api](https://github.com/coddingtonbear/obsidian-local-rest-api)). This is the foundational plugin most other servers build on.
- **`cyanheads/obsidian-mcp-server`** supports **both STDIO and Streamable HTTP** (selectable via `MCP_TRANSPORT_TYPE`), so Hermes can talk to it locally or over HTTP ([github.com/cyanheads/obsidian-mcp-server](https://github.com/cyanheads/obsidian-mcp-server)). It **wraps the Local REST API plugin (v4.0.0+)**, authenticates with an API key, defaults to `http://127.0.0.1:27123` ([github.com/cyanheads/obsidian-mcp-server](https://github.com/cyanheads/obsidian-mcp-server)), and provides **14 tools** including the full write set — `obsidian_write_note` (create/replace, refuses whole-file clobber without `overwrite:true`), `obsidian_append_to_note`, `obsidian_patch_note` (surgical section edits), `obsidian_replace_in_note`, `obsidian_delete_note` ([github.com/cyanheads/obsidian-mcp-server](https://github.com/cyanheads/obsidian-mcp-server)).
- **`MarkusPfundstein/mcp-obsidian`** "interact[s] with Obsidian via the Local REST API community plugin" (default `127.0.0.1:27124`), exposing read (`get_file_contents`, `list_files_in_vault`), search, and write tools — `patch_content` (insert relative to heading/block/frontmatter), `append_content` (new or existing file), `delete_file` ([github.com/MarkusPfundstein/mcp-obsidian](https://github.com/MarkusPfundstein/mcp-obsidian)).
- **`aaronsb/obsidian-mcp-plugin`** is the standout if you want **zero external dependency**: it embeds its own HTTP (3001) / HTTPS (3443, auto-generated self-signed cert) MCP server *inside* Obsidian with bearer auth, "without REST API overhead" ([github.com/aaronsb/obsidian-mcp-plugin](https://github.com/aaronsb/obsidian-mcp-plugin)). It exposes read+write — "list, read, create, search, move, split, combine" plus "window editing, append, patch sections" ([github.com/aaronsb/obsidian-mcp-plugin](https://github.com/aaronsb/obsidian-mcp-plugin)) — **and** the graph-traversal tools noted in §2 ([github.com/aaronsb/obsidian-mcp-plugin](https://github.com/aaronsb/obsidian-mcp-plugin)).

**Recommendation:** Use **`obsidian-local-rest-api` as the foundation** (it's the most widely depended-upon and now has its own MCP endpoint), and put **`cyanheads/obsidian-mcp-server`** in front of it for the clean 14-tool agent surface with STDIO/HTTP flexibility. If you prefer a single self-contained plugin with graph tools built in, **`aaronsb/obsidian-mcp-plugin`** is the strongest all-in-one. Whichever you pick, this fully satisfies the "API layer that can WRITE updates" requirement.

### REST + WebSocket for the dashboard (FastAPI)

Front the MCP layer and the RAG index with a **FastAPI** service that gives your dashboard plain REST for queries/graph JSON and a **WebSocket** for live push. FastAPI declares WebSocket endpoints with the `@app.websocket()` decorator on an async function that receives a `WebSocket`, calls `await websocket.accept()`, then loops on `await websocket.receive_text()`/`send_text()` ([fastapi.tiangolo.com/advanced/websockets](https://fastapi.tiangolo.com/advanced/websockets/)). Crucially for structured status events, FastAPI WebSockets also support **`send_json()`/`receive_json()`**, so Hermes can push structured event/status messages (task started, file changed, node updated) to the dashboard ([fastapi.tiangolo.com/advanced/websockets](https://fastapi.tiangolo.com/advanced/websockets/)).

**Suggested Hermes API surface:**
- `GET /graph` → `{nodes, links}` JSON for the visualization
- `POST /rag/query` → semantic search over the vault (proxies to `obsidian-notes-rag` MCP `search_notes`)
- `POST /notes` / `PATCH /notes/{path}` → create/edit markdown (proxies to a write-capable MCP server)
- `WS /ws/events` → live agent status/log/diff stream to the dashboard (`send_json`)

The WebSocket channel is what makes the "live panels" feel alive: the agent (or a file-watcher) pushes JSON events; the front-end subscribes and updates panels and, e.g., re-colors or pulses graph nodes as their notes change.

---

## 4. Tauri vs Electron desktop shell

**Important honesty note:** the verified claim set contained **no** claims about Tauri, Electron, WebGL embedding performance, tray/hotkeys, or bundling. Everything in this section is general engineering knowledge as of the model's training, **not** from the adversarially verified material — please re-verify against current Tauri/Electron docs before committing.

### Recommendation: **Tauri** for the VAULT shell.

Reasoning (general knowledge, directional):

- **WebGL-heavy UI:** Both use the system/Chromium web engine to run your Three.js/R3F canvas; a bloom-lit force graph is GPU-bound in the GPU driver, so raw WebGL throughput is comparable. Tauri uses the OS webview (WebKitGTK on Linux, WebView2 on Windows), which on Linux means you should test your specific bloom/postprocessing stack against WebKitGTK, as WebGL2/extension support can occasionally lag Chromium. Electron guarantees a known Chromium/V8 across platforms, which de-risks WebGL edge cases at the cost of size.
- **Bundle size & memory:** Tauri ships a tiny Rust binary + system webview (tens of MB, lower RAM); Electron bundles full Chromium+Node (100+ MB, higher RAM). For an always-on desktop HUD, Tauri's footprint is a real advantage.
- **Native window, system tray, global hotkeys:** Both support these. Tauri has first-class tray and global-shortcut plugins; Electron has `Tray` and `globalShortcut`. Parity here.
- **Direct local filesystem access to the vault:** Tauri (Rust backend) gives you fast, permissioned native FS access and a clean `#[tauri::command]` IPC boundary — ideal for reading the Obsidian vault directly and for a Rust-side file-watcher feeding the graph. Electron reaches the FS through Node in the main process.
- **IPC to a Python/Rust backend:** If Hermes/RAG is **Python (FastAPI)**, you'll run it as a sidecar in either shell and talk HTTP/WebSocket to it — Tauri has a documented "sidecar" mechanism to bundle and spawn that process. If you want maximal native performance and are willing to write Rust, Tauri lets you fold parts of the backend (vault watching, graph building) directly into the shell.

**When to choose Electron instead:** if you hit WebKitGTK WebGL incompatibilities with your postprocessing stack, or you want a single guaranteed Chromium across Linux/Windows and don't care about size/RAM. Given your Linux, AMD-GPU, always-on-HUD context, **Tauri is the better default**, but budget time to validate the bloom pipeline on WebKitGTK early.

---

## 5. AMD ROCm dual-GPU local serving

**Important honesty note:** the verified claim set contained **no** claims about ROCm, RDNA4/RDNA3 support, llama.cpp, vLLM, Ollama, or LM Studio. This entire section is general knowledge as of the model's early-2026 cutoff and **cannot be treated as verified for July 2026 state** — ROCm hardware support moves fast, so **verify current ROCm release notes for your exact cards before buying/committing.**

Your hardware: **AMD Radeon AI PRO R9700 32GB (RDNA4)** + **Radeon RX 7900 XTX 24GB (RDNA3)**, on Linux.

### ROCm status (directional, verify)

- **RDNA3 (7900 XTX, gfx1100):** Has been officially supported by ROCm for some time and is the most battle-tested consumer AMD card for LLM inference. Expect solid support across the stack.
- **RDNA4 (R9700, gfx12xx):** Newer; ROCm added RDNA4 support over 2025. By mid-2026 support should be maturing but may still trail RDNA3 in some frameworks. **Check the ROCm version's supported-GPU matrix and each serving framework's release notes** for gfx12 before assuming full support.

### Serving stack options (general knowledge)

- **llama.cpp:** The most flexible for heterogeneous/consumer AMD. Two AMD backends: **ROCm/HIP** (best perf when your cards are supported) and **Vulkan** (broader hardware support, often "just works" across mixed AMD GPUs, slightly lower peak perf). For **two different-architecture cards**, Vulkan is often the pragmatic path because it sidesteps ROCm arch-matrix gaps. llama.cpp supports splitting a model across GPUs *or* running separate instances per GPU.
- **vLLM (ROCm):** High-throughput serving with a ROCm build; excellent for a single large model with high concurrency, but historically pickier about GPU arch support and multi-GPU that's homogeneous. Better suited to running one model on the 32GB R9700 than to spanning two mismatched cards.
- **Ollama (ROCm):** Easiest UX; wraps llama.cpp with ROCm. Good for quick per-card model serving. Multi-GPU handling is more opaque.
- **LM Studio:** GUI, supports ROCm/Vulkan backends; convenient for experimentation but less suited as a headless production server than llama.cpp/vLLM.

### Running two cards + task-farming pattern (to save API tokens)

For coding sub-tasks, **treat the two GPUs as two independent workers rather than one split pool** (mismatched VRAM/arch makes tensor-splitting across them awkward and slow):

- **R9700 32GB (RDNA4):** run the larger coding model (fits a bigger quant / longer context) — your "senior" worker.
- **7900 XTX 24GB (RDNA3):** run a second instance (same or smaller model) — your "junior"/parallel worker.
- Launch each as a separate llama.cpp/Ollama server bound to a specific GPU (e.g., `HIP_VISIBLE_DEVICES=0` and `=1`, or `CUDA_VISIBLE_DEVICES` equivalents / Vulkan device index), each on its own port.
- **Orchestration:** Put a small dispatcher (part of Hermes) in front that farms coding sub-tasks to whichever card is free — a simple work queue with two OpenAI-compatible endpoints (llama.cpp exposes an OpenAI-compatible server). Route "hard/long-context" tasks to the 32GB card, "cheap/parallel" tasks to the 24GB card, and only escalate to a paid API when both local workers fail or a task exceeds local model capability. This is the token-saving pattern: **local-first, API-fallback**, with two concurrent local lanes.

Because everything speaks the OpenAI-compatible API, the same dispatcher generalizes to the later ComfyUI/video modules (see §6).

---

## 6. Build-agent telemetry + modular integration

**Honesty note:** the verified material contained **no** claims about Plane, Grafana, or agent-telemetry streaming. This section is general engineering guidance; verify Plane/Grafana specifics against their current docs.

### Surfacing "what the models are building right now"

The mechanism you already have from §3 is the right one: the **FastAPI WebSocket `send_json` channel** ([fastapi.tiangolo.com/advanced/websockets](https://fastapi.tiangolo.com/advanced/websockets/)) is how you stream live agent state to a dashboard panel. Concretely:

- Have each build-agent emit structured events — `{type:"task_start", id, title}`, `{type:"file_diff", path, diff}`, `{type:"log", line}`, `{type:"task_done", id, status}` — to the Hermes API, which fans them out over the WebSocket to a "Live Build" panel.
- For the **current file/diff**, stream `git diff` (or the agent's proposed patch) as it's produced; render it in a diff panel. For **logs**, tail the agent's stdout into the same channel.

### Plane (self-hosted kanban) integration

Plane exposes a **REST API** (issues, cycles, modules) and **webhooks** (general knowledge — verify against Plane's current API docs). Pattern:
- **Outbound:** when Hermes starts/finishes a coding sub-task, create/update a Plane issue via its API so the kanban reflects real agent work.
- **Inbound:** subscribe to Plane webhooks so that moving a card (e.g., to "In Progress") can *trigger* a Hermes task. This gives you a human-in-the-loop board that both mirrors and drives the agents.

### Grafana Cloud panels

Embed Grafana panels in a dashboard panel via **panel share/embed URLs or iframe embedding** (verify current Grafana Cloud embedding/auth options — some require public dashboards or signed embedding). Use Grafana for the quantitative telemetry — GPU utilization/VRAM/temps of your two AMD cards (via an exporter), tokens saved vs. API fallback counts, task throughput. This keeps the bespoke React panels for qualitative/live-diff views and offloads time-series charts to Grafana.

### Modular plugin architecture (for later video / ComfyUI dual-card modules)

Design Hermes as a **module registry** from day one so new capabilities slot in without touching the core:

- **Uniform module contract:** each module (RAG, build-agent, video-gen, ComfyUI image-gen) registers (a) REST routes, (b) a set of WebSocket event types it emits, and (c) optionally a dashboard panel component. The core just discovers and mounts them.
- **Consistent transport:** everything speaks HTTP + the shared WebSocket event bus, and local models speak the OpenAI-compatible API, so a **ComfyUI dual-card image module** or a **short-film video-generation module** is just another worker + panel — it publishes progress events to the same `send_json` stream and, for GPU work, plugs into the same two-card dispatcher from §5 (e.g., ComfyUI can pin different workflows to each GPU).
- **Graph as the hub:** since the vault graph is your central object, new modules can attach outputs back into Obsidian (write a note via the MCP write layer) and thus appear as new nodes in the visualization — closing the loop between generation and knowledge base.

This modularity costs little upfront and is what lets VAULT grow from "knowledge graph + coding agents" into a full multi-modal AI-OS.

---

## Caveats & time-sensitivity

- **Coverage is uneven.** The verified claim set is deep and high-confidence (all 3-0 votes, primary sources) on **§1 visualization** and **§2–3 Obsidian/RAG/MCP/FastAPI**. It contains **no verified claims** for **§4 (Tauri vs Electron), §5 (AMD ROCm), or §6 (Plane/Grafana/telemetry)**. Those three sections are general engineering knowledge flagged inline and should be independently re-verified.
- **ROCm and RDNA4 move fast.** RDNA4 (R9700) ROCm support in particular was maturing through 2025–2026; do not commit to a serving framework until you confirm your exact ROCm version supports gfx12 in llama.cpp/vLLM/Ollama. Vulkan (llama.cpp) is the safer fallback for a mismatched two-card setup.
- **Tauri + WebKitGTK WebGL risk.** Validate your full bloom/postprocessing pipeline on Linux WebKitGTK *early*; if it misbehaves, Electron's guaranteed Chromium is the escape hatch.
- **cosmos.gl vs Three.js tradeoff.** cosmos.gl scales to 100k+ nodes ([github.com/cosmosgl/graph](https://github.com/cosmosgl/graph)) but is 2D-first and doesn't give the same per-node custom 3D glow objects; the VAULT aesthetic at 1k–10k nodes is a Three.js/R3F job.
- **"No network calls" is scoped.** `obsidian-notes-rag`'s no-telemetry/no-network guarantee is about **storage**; using a cloud embedding provider still makes network calls ([github.com/proofgeist/obsidian-notes-rag](https://github.com/proofgeist/obsidian-notes-rag)). Use a local embedding model for a fully offline pipeline.
- **Port/default nuances across MCP servers.** Different servers assume different Local REST API ports (27123 HTTP vs 27124 HTTPS) and versions (cyanheads needs Local REST API **v4.0.0+**) — align these carefully ([github.com/cyanheads/obsidian-mcp-server](https://github.com/cyanheads/obsidian-mcp-server); [github.com/MarkusPfundstein/mcp-obsidian](https://github.com/MarkusPfundstein/mcp-obsidian)).
- **Smart Connections / khoj / basic-memory / LanceDB / Chroma / Qdrant / deck.gl / Sigma.js** were named in your brief but did **not** appear in the verified claims — I did not fabricate specifics for them.

## Open questions

1. **Vault scale:** Roughly how many notes/links? This decides Three.js/R3F (≤10k) vs a cosmos.gl "huge vault" module (100k+).
2. **Backend language:** Python (FastAPI) for RAG/Hermes, or fold parts into Rust for a tighter Tauri integration? Affects the sidecar vs native-command IPC design.
3. **Which single MCP write server** becomes canonical for Hermes — the self-contained `aaronsb/obsidian-mcp-plugin` (graph tools built in) or the `Local REST API` + `cyanheads` stack (cleaner 14-tool surface)? Both are verified; pick one to avoid port/auth sprawl.
4. **Two-card strategy:** independent per-card workers (recommended for mismatched VRAM) vs attempting a split — needs a benchmark on your actual ROCm/Vulkan build.
5. **Selective bloom fidelity:** do you want *only nodes* to bloom (selective bloom pass) while panels/text stay crisp? That changes the postprocessing setup (layers/selective composer) beyond the basic `Bloom` component.
6. **Color-shift semantics:** should node color encode *meaning* (recency, cluster, agent activity) or be purely aesthetic time-cycling? This affects whether color is data-driven from the graph/RAG layer or a pure shader animation.
7. **Live-diff source of truth:** stream diffs from git, from the agent's proposed patches, or from the Obsidian write events? Determines how the "Live Build" panel is wired.

---

## Appendix: verified claims (all passed 3-0 adversarial verification)

- **3d-force-graph renders a force-directed graph in 3D using ThreeJS/WebGL, exposing node click and hover handlers (onNodeClick, onNodeHover) suitable for wiring node selection to opening a linked Obsidian note.**  
  — _primary_ · [https://github.com/vasturiano/3d-force-graph](https://github.com/vasturiano/3d-force-graph) · quote: "ThreeJS/WebGL for 3D rendering"
- **The library exposes the post-processing composer via postProcessingComposer(), allowing addition of Three.js rendering effects such as UnrealBloom for the glowing/bloom-lit aesthetic.**  
  — _primary_ · [https://github.com/vasturiano/3d-force-graph](https://github.com/vasturiano/3d-force-graph) · quote: "access the post-processing composer"
- **Nodes can be rendered with arbitrary custom Three.js geometry/materials through nodeThreeObject(), which accepts ThreeJS Object3d instances, enabling particle/glow node materials.**  
  — _primary_ · [https://github.com/vasturiano/3d-force-graph](https://github.com/vasturiano/3d-force-graph) · quote: "ThreeJS Object3d instances"
- **r3f-forcegraph provides React Three Fiber bindings for the three-forcegraph component, letting a force-directed graph be rendered as a native R3F component within a Three.js/R3F scene rather than as a standalone canvas.**  
  — _primary_ · [https://github.com/vasturiano/r3f-forcegraph](https://github.com/vasturiano/r3f-forcegraph) · quote: "React-Three-Fiber bindings for the three-forcegraph ThreeJS component."
- **The library supports fully custom Three.js node objects via the nodeThreeObject accessor, enabling custom geometry and particle/glow materials for each node (needed for the Karpathy-style glowing particle nodes).**  
  — _primary_ · [https://github.com/vasturiano/r3f-forcegraph](https://github.com/vasturiano/r3f-forcegraph) · quote: "Node object accessor function or attribute for generating a custom 3d object to render as graph nodes"
- **Nodes and links expose click callbacks (onNodeClick, onLinkClick) so a clicked node can be mapped to an action such as opening its linked Obsidian markdown note.**  
  — _primary_ · [https://github.com/vasturiano/r3f-forcegraph](https://github.com/vasturiano/r3f-forcegraph) · quote: "Node and link click callbacks: onNodeClick, onLinkClick"
- **cosmos.gl (the engine powering Cosmograph) is a WebGL2-based force graph engine that runs all layout computation and rendering on the GPU via fragment/vertex shaders, avoiding expensive CPU memory operations.**  
  — _primary_ · [https://github.com/cosmosgl/graph](https://github.com/cosmosgl/graph) · quote: "All the computations and drawing occur on the GPU in fragment and vertex shaders, avoiding expensive memory operations"
- **cosmos.gl can render and simulate network graphs of hundreds of thousands of nodes and links in real time on modern hardware, exceeding the 1k-10k+ scale target for a large Obsidian vault graph.**  
  — _primary_ · [https://github.com/cosmosgl/graph](https://github.com/cosmosgl/graph) · quote: "network graphs consisting of hundreds of thousands of points and links on modern hardware"
- **react-postprocessing (@react-three/postprocessing) provides a Bloom effect for react-three-fiber, enabling glow/bloom lighting on a Three.js scene with minimal code.**  
  — _primary_ · [https://github.com/pmndrs/react-postprocessing](https://github.com/pmndrs/react-postprocessing) · quote: "Supported Effects (from example)... Bloom"
- **obsidian-notes-rag stores vector embeddings locally using sqlite-vec (via vec0 virtual tables for KNN search), replacing ChromaDB as of v1.0.0, with metadata stored in SQLite and no network calls or telemetry.**  
  — _primary_ · [https://github.com/proofgeist/obsidian-notes-rag](https://github.com/proofgeist/obsidian-notes-rag) · quote: "Stores vectors locally in sqlite-vec (~200KB, no telemetry, no network calls)."
- **The tool ships an MCP server (invoked via `obsidian-rag serve`) that exposes semantic search and related-content retrieval to any MCP-compatible AI assistant, matching the research question's need for an Obsidian RAG backend accessible to agents.**  
  — _primary_ · [https://github.com/proofgeist/obsidian-notes-rag](https://github.com/proofgeist/obsidian-notes-rag) · quote: "As an MCP server, it gives any compatible AI assistant the same capabilities — searching your notes, finding related content, and pulling context during conversations."
- **obsidian-local-rest-api is an Obsidian plugin exposing full CRUD (read/create/update/delete) on any file in the vault via a secure REST API, enabling AI agents to programmatically read and write markdown notes — directly satisfying the 'API layer that can WRITE updates' requirement for the Hermes agent.**  
  — _primary_ · [https://github.com/coddingtonbear/obsidian-local-rest-api](https://github.com/coddingtonbear/obsidian-local-rest-api) · quote: "Read, create, update, or delete notes — full CRUD on any file in your vault"
- **The plugin ships a built-in MCP server at the /mcp/ endpoint using Streamable HTTP transport, providing tools for vault operations, file patching, search, tags, and command execution — meaning an MCP-native agent can connect without a separate obsidian-mcp bridge.**  
  — _primary_ · [https://github.com/coddingtonbear/obsidian-local-rest-api](https://github.com/coddingtonbear/obsidian-local-rest-api) · quote: "Built-in MCP server at `/mcp/` using "Streamable HTTP" transport with the same authentication requirements. Available tools include vault operations, file patching, search, tags, and command execution."
- **The obsidian-mcp-plugin implements its own HTTP/HTTPS MCP server embedded in Obsidian (HTTP port 3001, HTTPS port 3443 with auto-generated self-signed cert, bearer-token auth) rather than relying on the Obsidian Local REST API plugin.**  
  — _primary_ · [https://github.com/aaronsb/obsidian-mcp-plugin](https://github.com/aaronsb/obsidian-mcp-plugin) · quote: "HTTP: Port 3001 (default) ... HTTPS: Port 3443 (self-signed certificate auto-generated) ... Clients connect via HTTP headers with bearer token authentication"
- **The plugin exposes read AND write access to vault markdown, letting an agent list, read, create, search, move, split, and combine notes plus window editing, append, and section patching -- directly usable as Hermes' write layer.**  
  — _primary_ · [https://github.com/aaronsb/obsidian-mcp-plugin](https://github.com/aaronsb/obsidian-mcp-plugin) · quote: "Vault: list, read, create, search, move, split, combine ... Edit: window editing, append, patch sections"
- **The plugin provides dedicated graph-traversal tools (traverse, find paths, analyze connections) that let an agent navigate the vault's wikilink structure, supplying graph data for both visualization and RAG context.**  
  — _primary_ · [https://github.com/aaronsb/obsidian-mcp-plugin](https://github.com/aaronsb/obsidian-mcp-plugin) · quote: "Graph: traverse, find paths, analyze connections"
- **An Obsidian plugin (Local REST API Second Brain MCP Extension) exposes a Model Context Protocol endpoint at /second-brain-mcp/ that layers on top of the Obsidian Local REST API plugin, reusing its authentication and web server rather than running its own.**  
  — _primary_ · [https://community.obsidian.md/plugins/local-rest-api-second-brain-mcp-extension](https://community.obsidian.md/plugins/local-rest-api-second-brain-mcp-extension) · quote: "The plugin exposes a Model Context Protocol endpoint at `/second-brain-mcp/`, leveraging the parent plugin's secure infrastructure without managing its own authentication or web servers."
- **The plugin combines local-embedding semantic search (using models like all-MiniLM-L6-v2) with breadth-first traversal of Obsidian's internal link graph across both outgoing links and backlinks to retrieve contextually related notes.**  
  — _primary_ · [https://community.obsidian.md/plugins/local-rest-api-second-brain-mcp-extension](https://community.obsidian.md/plugins/local-rest-api-second-brain-mcp-extension) · quote: "Uses local embedding models (e.g., `all-MiniLM-L6-v2`) for semantic search ... Executes breadth-first search across Obsidian's internal link graph—traversing both outgoing links and backlinks to gather contextual information"
- **cyanheads/obsidian-mcp-server exposes both STDIO and Streamable HTTP MCP transports, selectable via the MCP_TRANSPORT_TYPE environment variable, making it usable by an autonomous agent locally or over HTTP.**  
  — _primary_ · [https://github.com/cyanheads/obsidian-mcp-server](https://github.com/cyanheads/obsidian-mcp-server) · quote: "The server supports two MCP transports: **STDIO and Streamable HTTP**. Configuration example shows "type": "stdio" with MCP_TRANSPORT_TYPE environment variable supporting both modes."
- **The server connects to an Obsidian vault by wrapping the Obsidian Local REST API plugin (v4.0.0+), authenticating with an API key and defaulting to http://127.0.0.1:27123.**  
  — _primary_ · [https://github.com/cyanheads/obsidian-mcp-server](https://github.com/cyanheads/obsidian-mcp-server) · quote: "The server "wraps the Obsidian Local REST API plugin" and requires version "4.0.0 or later" installed in your vault. Connection uses an API key from plugin settings, defaulting to http://127.0.0.1:27123."
- **It provides 14 tools including write operations (obsidian_write_note, obsidian_append_to_note, obsidian_patch_note for surgical edits, obsidian_replace_in_note, obsidian_delete_note) that let an agent create and edit markdown notes programmatically.**  
  — _primary_ · [https://github.com/cyanheads/obsidian-mcp-server](https://github.com/cyanheads/obsidian-mcp-server) · quote: "obsidian_write_note creates files or "surgically replace" via targeted edits. obsidian_append_to_note handles "upsert + section-append." obsidian_patch_note performs "surgical edits at a single document target" using append/prepend/replace operations."
- **mcp-obsidian is an MCP server that lets an AI agent read, search, and write to an Obsidian vault by bridging to the Obsidian Local REST API community plugin (default host 127.0.0.1, port 27124).**  
  — _primary_ · [https://github.com/MarkusPfundstein/mcp-obsidian](https://github.com/MarkusPfundstein/mcp-obsidian) · quote: "MCP server to interact with Obsidian via the Local REST API community plugin"
- **The server exposes write tools that let an agent create and modify markdown notes: patch_content inserts content relative to a heading/block/frontmatter, append_content appends to a new or existing file, and delete_file removes files.**  
  — _primary_ · [https://github.com/MarkusPfundstein/mcp-obsidian](https://github.com/MarkusPfundstein/mcp-obsidian) · quote: "patch_content: Insert content into an existing note relative to a heading, block reference, or frontmatter field ... append_content: Append content to a new or existing file in the vault ... delete_file: Delete a file or directory from your vault"
- **FastAPI declares WebSocket endpoints with the @app.websocket() decorator on an async function that receives a WebSocket object, calls await websocket.accept(), then loops on await websocket.receive_text()/send_text() to exchange messages.**  
  — _primary_ · [https://fastapi.tiangolo.com/advanced/websockets/](https://fastapi.tiangolo.com/advanced/websockets/) · quote: "@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    while True:
        data = await websocket.receive_text()
        await websocket.send_text(f"Message text was: {data}")"
- **FastAPI WebSockets support JSON send/receive (send_json/receive_json) in addition to text, enabling structured event/status messages to be pushed to a dashboard.**  
  — _primary_ · [https://fastapi.tiangolo.com/advanced/websockets/](https://fastapi.tiangolo.com/advanced/websockets/) · quote: "`await websocket.receive_json()` / `await websocket.send_json()` - Handle JSON data"

### Sources fetched

- [https://github.com/vasturiano/3d-force-graph](https://github.com/vasturiano/3d-force-graph) — primary · 3D graph visualization · 5 claims
- [https://github.com/vasturiano/r3f-forcegraph](https://github.com/vasturiano/r3f-forcegraph) — primary · 3D graph visualization · 5 claims
- [https://github.com/cosmosgl/graph](https://github.com/cosmosgl/graph) — primary · 3D graph visualization · 5 claims
- [https://github.com/vasturiano/react-force-graph/issues/223](https://github.com/vasturiano/react-force-graph/issues/223) — forum · 3D graph visualization · 5 claims
- [https://github.com/vasturiano/3d-force-graph/issues/321](https://github.com/vasturiano/3d-force-graph/issues/321) — forum · 3D graph visualization · 3 claims
- [https://github.com/pmndrs/react-postprocessing](https://github.com/pmndrs/react-postprocessing) — primary · 3D graph visualization · 5 claims
- [https://github.com/proofgeist/obsidian-notes-rag](https://github.com/proofgeist/obsidian-notes-rag) — primary · Obsidian graph + RAG backend · 5 claims
- [https://github.com/ferparra/graph-rag-mcp-server](https://github.com/ferparra/graph-rag-mcp-server) — unreliable · Obsidian graph + RAG backend · 0 claims
- [https://github.com/coddingtonbear/obsidian-local-rest-api](https://github.com/coddingtonbear/obsidian-local-rest-api) — primary · Obsidian graph + RAG backend · 5 claims
- [https://github.com/aaronsb/obsidian-mcp-plugin](https://github.com/aaronsb/obsidian-mcp-plugin) — primary · Obsidian graph + RAG backend · 5 claims
- [https://community.obsidian.md/plugins/local-rest-api-second-brain-mcp-extension](https://community.obsidian.md/plugins/local-rest-api-second-brain-mcp-extension) — primary · Obsidian graph + RAG backend · 5 claims
- [https://motherduck.com/blog/obsidian-rag-duckdb-motherduck/](https://motherduck.com/blog/obsidian-rag-duckdb-motherduck/) — blog · Obsidian graph + RAG backend · 5 claims
- [https://github.com/cyanheads/obsidian-mcp-server](https://github.com/cyanheads/obsidian-mcp-server) — primary · Agent API + live push layer · 5 claims
- [https://github.com/MarkusPfundstein/mcp-obsidian](https://github.com/MarkusPfundstein/mcp-obsidian) — primary · Agent API + live push layer · 4 claims
- [https://fastapi.tiangolo.com/advanced/websockets/](https://fastapi.tiangolo.com/advanced/websockets/) — primary · Agent API + live push layer · 5 claims
- [https://www.gethopp.app/blog/tauri-vs-electron](https://www.gethopp.app/blog/tauri-vs-electron) — blog · Tauri vs Electron desktop shell · 5 claims
- [https://peerlist.io/jagss/articles/tauri-vs-electron-a-deep-technical-comparison](https://peerlist.io/jagss/articles/tauri-vs-electron-a-deep-technical-comparison) — unreliable · Tauri vs Electron desktop shell · 0 claims
- [https://www.levminer.com/blog/tauri-vs-electron](https://www.levminer.com/blog/tauri-vs-electron) — blog · Tauri vs Electron desktop shell · 5 claims
- [https://github.com/tlee933/llama.cpp-rdna4-gfx1201](https://github.com/tlee933/llama.cpp-rdna4-gfx1201) — blog · AMD ROCm dual-GPU LLM serving · 5 claims
- [https://github.com/ggml-org/llama.cpp/discussions/21043](https://github.com/ggml-org/llama.cpp/discussions/21043) — forum · AMD ROCm dual-GPU LLM serving · 5 claims
- [https://digtvbg.com/blog/llama-server-vulkan-rdna4-vllm-rocm-benchmark/](https://digtvbg.com/blog/llama-server-vulkan-rdna4-vllm-rocm-benchmark/) — blog · AMD ROCm dual-GPU LLM serving · 5 claims
- [https://github.com/vllm-project/vllm/issues/28649](https://github.com/vllm-project/vllm/issues/28649) — forum · AMD ROCm dual-GPU LLM serving · 5 claims
- [https://developers.plane.so/dev-tools/intro-webhooks](https://developers.plane.so/dev-tools/intro-webhooks) — primary · Build-agent telemetry + modular integration · 5 claims
- [https://blog.marcnuri.com/ai-coding-agent-dashboard](https://blog.marcnuri.com/ai-coding-agent-dashboard) — blog · Build-agent telemetry + modular integration · 5 claims
- [https://github.com/puritysb/AgentDeck](https://github.com/puritysb/AgentDeck) — primary · Build-agent telemetry + modular integration · 5 claims
- [https://github.com/comfyanonymous/ComfyUI/blob/master/script_examples/websockets_api_example.py](https://github.com/comfyanonymous/ComfyUI/blob/master/script_examples/websockets_api_example.py) — primary · Build-agent telemetry + modular integration · 5 claims
- [https://grafana.com/blog/how-to-embed-grafana-dashboards-into-web-applications/](https://grafana.com/blog/how-to-embed-grafana-dashboards-into-web-applications/) — primary · Build-agent telemetry + modular integration · 5 claims

### Run stats

- Angles: 6
- Sources fetched: 27
- Claims extracted: 122
- Claims verified: 25
- Confirmed: 25 · Refuted: 0 · Unverified: 0

---

# ADDENDUM — Targeted follow-up (2026-07-03): §5 ROCm/RDNA4 and §4 Tauri now VERIFIED

The two sections flagged above as "general knowledge, not verified" were re-researched against current, dated primary sources (ROCm 7.2.x docs, llama.cpp/vLLM/Ollama GitHub issues & release notes, Tauri/wry issues, WebKitGTK release highlights). These findings **supersede** §4 and §5 above.

## §5 (revised) — AMD ROCm dual-GPU serving: **GO-WITH-CAVEATS**

**R9700 (RDNA4, gfx1201) IS officially supported** — but only in **ROCm 7.x** (no 6.x support). Listed by name on the ROCm 7.2.x supported-GPU matrix. Supported OS incl. Ubuntu 24.04.x. ([ROCm compatibility matrix](https://rocm.docs.amd.com/en/latest/compatibility/compatibility-matrix.html))

**Key reversals / gotchas vs the earlier general guidance:**
- **Vulkan (llama.cpp) is the RELIABLE path on RDNA4, not ROCm/HIP.** ROCm/HIP has an open **idle-power bug on gfx1201** — with the HIP runtime resident the card stays pinned at 100% clocks/util and never idles until the process exits ([ROCm#5706](https://github.com/ROCm/ROCm/issues/5706), [ROCm#6298](https://github.com/ROCm/ROCm/issues/6298)). Vulkan does NOT show this. Vulkan also *beat* vLLM-ROCm 62 vs 48 t/s on the same gfx1201 silicon ([benchmark](https://digtvbg.com/blog/llama-server-vulkan-rdna4-vllm-rocm-benchmark/)).
- **No `HSA_OVERRIDE_GFX_VERSION` hack needed** — gfx1201 is a real listed target in ROCm 7.
- **vLLM-ROCm: single-GPU (TP=1) works; multi-GPU is BROKEN.** `--tensor-parallel-size 2` deadlocks even on dual *same-arch* R9700s ([vllm#40980](https://github.com/vllm-project/vllm/issues/40980), open 2026-04). Requires `VLLM_ROCM_USE_AITER=0` on RDNA4 (AITER kernels don't run on RDNA4) ([FP8 WMMA thread](https://discuss.vllm.ai/t/native-fp8-wmma-support-for-amd-rdna4-rx-9070-xt-r9700-in-vllm/1900)).
- **Ollama supports RDNA4** from ~0.30.6 + ROCm 7.1 ([docs.ollama.com/gpu](https://docs.ollama.com/gpu)).
- **Mixed gfx1100 + gfx1201 tensor-split: untested/highest-risk.** No primary source validates splitting one model across the two different architectures. Even same-arch dual-GPU is broken (above).

**Recommended setup (locked): two INDEPENDENT single-GPU processes, NOT a tensor-split.**
1. Base: ROCm 7.2.x on Ubuntu 24.04.x.
2. `llama-server` with the **Vulkan backend** on BOTH cards (OpenAI-compatible `/v1`), each pinned via `HIP_VISIBLE_DEVICES` (or Vulkan device index) on its own port.
   - R9700 32GB → larger coding model (30B-class MoE / 14B dense long-context) = "senior" worker.
   - 7900 XTX 24GB (mature RDNA3) → smaller/fast model = "junior"/parallel worker.
3. Thin router in front (part of Hermes) → local-first, fail over to paid API on error/timeout.
4. Only reach for vLLM-ROCm (TP=1, R9700 only) if you specifically need FP8/high-throughput serving. Never TP≥2.

**Note for your Grafana panels:** the gfx1201 idle-power bug means a HIP/ROCm-resident process pins the R9700 at 100% util regardless of real work — so if you go the ROCm route, GPU-util is NOT a reliable "is it actually building" signal. Another reason to prefer Vulkan (idles correctly) and to stream real task/diff events (§3, §6) instead of inferring activity from heat.

**Verify on your own hardware:** the "fixed" status of the idle-power bug, and any mixed-arch split.

## §4 (revised) — Tauri vs Electron: **GO-WITH-CAVEATS on Tauri, because you're on AMD**

AMD/Mesa/RADV is the *favorable* WebKitGTK case — nearly all the notorious blank-window/GBM breakage is **NVIDIA-specific** ([Tauri#9394](https://github.com/tauri-apps/tauri/issues/9394), [Linux Graphics docs](https://v2.tauri.app/develop/debug/linux-graphics/)). WebKitGTK does WebGL2 via ANGLE (same layer as Chromium), so `EXT_color_buffer_float`/half-float RTs that UnrealBloom needs are generally available.

**But two real risks:**
- **Silent software-rendering fallback.** WebGL2 context creation succeeds even when backed by a software rasterizer; you **cannot** detect it via the renderer string (WebKitGTK reports "Apple GPU" on all Linux for fingerprint protection) ([Linux Graphics docs](https://v2.tauri.app/develop/debug/linux-graphics/)). Detect empirically by measuring frame time with bloom active on startup.
- **[Tauri#6559 "WebGL context lost"](https://github.com/tauri-apps/tauri/issues/6559)** — three.js scenes fail in-app while working in-browser. Still open, `status: upstream`. This is exactly our stack.

**Decision gate + mitigations if proceeding with Tauri:**
1. **Prototype the actual force-graph + EffectComposer/UnrealBloom scene fullscreen on the real AMD target BEFORE committing.** If #6559 reproduces, switch to Electron.
2. Require **WebKitGTK ≥ 2.48** (prefer 2.50/2.52 for Skia GPU rendering + WebGL GPU process); enable `UseGPUProcessForWebGL`.
3. On AMD, do **NOT** reflexively set `WEBKIT_DISABLE_DMABUF_RENDERER=1` / `WEBKIT_DISABLE_COMPOSITING_MODE=1` — they force the slow/software path that kills bloom. Crash-only fallbacks.
4. Use `HalfFloatType` (not `FloatType`) bloom render targets; cap bloom resolution/mips.
5. Keep the front-end runtime-portable so an **Electron fallback** is cheap.

**When to just use Electron:** if bloom-at-framerate is mission-critical and you can't test on the exact target machine. Electron's bundled Chromium is the most-exercised WebGL path in existence; its size/RAM overhead is noise next to a Three.js+bloom scene. No 2025-2026 primary benchmark of Three.js+UnrealBloom on Tauri/AMD was found — that absence is itself a mild negative signal.

**Verify on hardware:** whether WebKitGTK 2.52 enables the WebGL GPU process by default (assume you must opt in); `EXT_color_buffer_float` + MRT pass on RADV.
