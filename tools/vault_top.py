#!/usr/bin/env python3
"""vault — the VAULT daily-driver TUI (Textual). Deck + command deck.

Run: `vault` (or tools/vault-top). Framework decision + patterns:
docs/TUI-DECISION-2026-07-04.md.

Layout (ku/lazygit style):
  ┌ deck: GPUs·tok/s · cloud orchestrator · running · history ┐  Tab: focus
  ├ transcript: streaming events for the active/selected task ┤  panes
  └ prompt line ─ /run /hermes /ask /cancel /quit ────────────┘  Esc: cancel

Events arrive over WS /ws/events (push); deck state polls every 5s for the
hardware/throughput numbers. Esc-interrupt = POST task-runner /cancel.
"""

from __future__ import annotations

import asyncio
import json
import shlex
import time
import webbrowser
from pathlib import Path

import requests
from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Input, RichLog, Static

ROOT = Path(__file__).resolve().parents[1]
SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧"

AMBER = "#ffb347"
CYAN = "#00e5ff"
MAGENTA = "#ff2bd6"
GREEN = "#7ddc8a"
RED = "#ff5f56"


def _env() -> dict:
    vals = {}
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, _, v = line.partition("=")
            vals[k.strip()] = v.strip()
    return vals


class TaskScreen(Screen):
    """Miller-column drill-down (Claude Code /workflows style).

    Left pane: task list — ↑/↓ move selection, right pane live-updates.
    →: focus the output pane (depth 2). j/k always scroll the output;
    at depth 2 ↑/↓ scroll it too. ←: back out a level, then back to deck.
    """

    BINDINGS = [
        ("escape", "app.pop_screen", "back"),
        ("left", "go_left", "back"),
        ("right", "go_right", "focus output"),
        ("up", "nav(-1)", "↑"),
        ("down", "nav(1)", "↓"),
        ("j", "scroll_output(3)", "scroll ↓"),
        ("k", "scroll_output(-3)", "scroll ↑"),
        ("ctrl+o", "open_issue", "open in Plane"),
        ("q", "app.quit", "quit"),
    ]
    CSS = f"""
    #drill-list {{
        width: 38; border: round {CYAN} 60%; padding: 0 1;
        border-title-color: {AMBER};
    }}
    #drill-output {{
        border: round {CYAN} 30%; padding: 0 1;
        border-title-color: {AMBER};
    }}
    #drill-list.pane-focused {{ border: round {CYAN}; }}
    #drill-output.pane-focused {{ border: round {CYAN}; }}
    """

    def __init__(self, task_ids: list[str], index: int) -> None:
        super().__init__()
        self.task_ids = task_ids or ["?"]
        self.index = index % len(self.task_ids)
        self.depth = 1  # 1 = list focused, 2 = output focused
        self.detail: dict = {}

    @property
    def task_id(self) -> str:
        return self.task_ids[self.index]

    def compose(self) -> ComposeResult:
        yield Horizontal(
            VerticalScroll(Static(id="list-body"), id="drill-list"),
            VerticalScroll(Static(id="output-body"), id="drill-output"),
        )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#drill-list").border_title = "TASKS"
        self._mark_focus()
        self.set_interval(2.0, self.refresh_detail)
        self.refresh_detail()

    # ── navigation ──────────────────────────────────────────────────────

    def action_nav(self, delta: int) -> None:
        if self.depth == 1:
            self.index = (self.index + delta) % len(self.task_ids)
            self.refresh_detail()
        else:
            self.action_scroll_output(delta * 3)

    def action_go_right(self) -> None:
        self.depth = 2
        self._mark_focus()

    def action_go_left(self) -> None:
        if self.depth == 2:
            self.depth = 1
            self._mark_focus()
        else:
            self.app.pop_screen()

    def action_scroll_output(self, lines: int) -> None:
        self.query_one("#drill-output", VerticalScroll).scroll_relative(
            y=lines, animate=False
        )

    def action_open_issue(self) -> None:
        url = self.detail.get("plane", {}).get("url")
        if url:
            webbrowser.open(url)

    def _mark_focus(self) -> None:
        lst = self.query_one("#drill-list")
        out = self.query_one("#drill-output")
        lst.set_class(self.depth == 1, "pane-focused")
        out.set_class(self.depth == 2, "pane-focused")

    # ── data + render ───────────────────────────────────────────────────

    def refresh_detail(self) -> None:
        app: "VaultTop" = self.app  # type: ignore[assignment]
        try:
            r = requests.get(
                f"{app.api}/modules/gpu-deck/task/{self.task_id}",
                headers=app.headers,
                timeout=4,
            )
            r.raise_for_status()
            self.detail = r.json()
        except requests.RequestException as e:
            self.detail = {"error": str(e)}
        self.redraw()

    def redraw(self) -> None:
        app: "VaultTop" = self.app  # type: ignore[assignment]
        # left: task list with cursor
        lst = Text()
        for i, tid in enumerate(self.task_ids):
            sel = "❯ " if i == self.index else "  "
            info = next(
                (t for t in app._tasks() if t["taskId"] == tid), {"taskId": tid}
            )
            mark = (
                "▶" if info.get("startedAt") and not info.get("status")
                else ("✓" if info.get("status") == "success" else "·")
            )
            style = f"bold {CYAN}" if i == self.index else "#cfe8f5"
            lst.append(f"{sel}{mark} {tid}\n", style=style)
            title = (info.get("title") or "")[:30]
            if title:
                lst.append(f"     {title}\n", style="dim")
        self.query_one("#list-body", Static).update(lst)

        # right: full transcript of the selected task
        d = self.detail
        out = Text()
        header = "…"
        if d.get("error"):
            out.append(d["error"], style=RED)
        else:
            info = d.get("info", {})
            header = f"{info.get('taskId', '?')} {info.get('title', '')}"[:60]
            p = d.get("plane", {})
            if p.get("linked"):
                out.append(
                    f"{p.get('project')} › {p.get('milestone')} › "
                    f"{p.get('issue')}\n",
                    style=MAGENTA,
                )
                out.append("ctrl+o opens in Plane\n\n", style="dim")
            else:
                out.append(f"{p.get('reason', 'unplanned')}\n\n", style="dim")
            for e in d.get("events", []):
                stamp = time.strftime("%H:%M:%S", time.localtime(e.get("ts", 0)))
                out.append(f"{stamp} ", style="dim")
                if e["type"] == "log":
                    style = RED if e.get("level") == "error" else "#cfe8f5"
                    out.append(f"{e.get('line', '')}\n", style=style)
                elif e["type"] == "file_diff":
                    out.append(f"⇄ diff {e.get('path')}\n", style=CYAN)
                    for dl in e.get("diff", "").splitlines():
                        ds = (
                            GREEN if dl.startswith("+")
                            else RED if dl.startswith("-")
                            else "dim"
                        )
                        out.append(f"  {dl}\n", style=ds)
                elif e["type"] == "task_start":
                    out.append("▶ task started\n", style=GREEN)
                elif e["type"] == "task_done":
                    out.append(f"■ done — {e.get('status')}\n", style=GREEN)
                else:
                    out.append(f"{e['type']}\n")
        self.query_one("#drill-output").border_title = header
        self.query_one("#output-body", Static).update(out)


class VaultTop(App):
    TITLE = "VAULT"
    BINDINGS = [
        ("ctrl+q", "quit", "quit"),
        ("escape", "cancel_task", "cancel task"),
        ("f1", "toggle_worker(0)", "worker 1"),
        ("f2", "toggle_worker(1)", "worker 2"),
        ("f3", "toggle_worker(2)", "worker 3"),
        ("ctrl+o", "open_issue", "open in Plane"),
        # priority: selection must work even while the prompt Input has focus
        Binding("up", "move(-1)", "select ↑", priority=True),
        Binding("down", "move(1)", "select ↓", priority=True),
        Binding("right", "drill_right", "drill →", priority=True),
        Binding("tab", "menu_tab", "complete", priority=True, show=False),
        ("enter", "drill", "drill down"),
    ]
    CSS = f"""
    Screen {{ background: #04060c; }}
    #deck {{ padding: 1 2; height: 1fr; }}
    #orchline {{ height: 1; padding: 0 2; background: #060a12; }}
    #cmdmenu {{
        height: auto; max-height: 14; padding: 0 2;
        background: #0a0f1a; border-top: solid {CYAN} 40%;
        display: none;
    }}
    #transcript {{
        height: 12; border-top: solid {CYAN} 30%;
        background: #04060c; color: #cfe8f5; padding: 0 2; display: none;
    }}
    #prompt {{
        dock: bottom; border: solid {CYAN} 40%;
        background: #060a12; color: {AMBER};
    }}
    """

    TAG_COLORS = [CYAN, MAGENTA, GREEN, "#7ddcff", "#c792ea", AMBER]

    # (command, usage, description) — drives the / palette and /help
    COMMANDS = [
        ("/run", "/run <cmd>", "run a shell command server-side, streamed live"),
        ("/hermes", "/hermes <prompt>",
         "cloud orchestrator, slim profile (~3.6k tok overhead)"),
        ("/hermes!", "/hermes! <prompt>",
         "cloud orchestrator, FULL profile: memory+toolsets (~12.5k tok)"),
        ("/ask", "/ask <prompt>",
         "local model router (free tokens; paid fallback if worker down)"),
        ("/models", "/models", "list local GGUFs (size, arch, loadability)"),
        ("/model", "/model [gpu] <n|name>",
         "switch a card's worker model (sticky across restarts)"),
        ("/cancel", "/cancel", "cancel the active task (same as Esc)"),
        ("/clear", "/clear", "clear and hide the transcript pane"),
        ("/reset-cloud", "/reset-cloud",
         "zero the cloud-orchestrator token window (records archived)"),
        ("/reset-ledger", "/reset-ledger",
         "zero the local/paid router token counters"),
        ("/help", "/help", "show this command reference"),
        ("/quit", "/quit", "exit vault (also ctrl+q)"),
    ]

    def __init__(self) -> None:
        super().__init__()
        env = _env()
        self.api = f"http://127.0.0.1:{env.get('HERMES_API_PORT', '8100')}"
        self.token = env.get("HERMES_API_TOKEN", "")
        self.headers = {"Authorization": f"Bearer {self.token}"}
        self.state: dict = {}
        self.tick = 0
        self.cursor = 0
        self.active_task: str | None = None
        self.cloud_live: list | None = []  # None = poll error
        # plain-text mirror of the transcript (drives tests + future export)
        self.transcript_lines: list[str] = []
        # slash-command palette state
        self.menu_items: list[tuple[str, str, str]] = []
        self.menu_idx = 0

    # ── layout ──────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(id="deck"),
            Static(id="orchline"),
            RichLog(id="transcript", markup=False, wrap=True, max_lines=500),
        )
        yield Static(id="cmdmenu")
        yield Input(
            placeholder="›  type / for commands · bare text = ask the local "
            "model · /help",
            id="prompt",
        )
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(5.0, self.refresh_state)
        self.set_interval(1.5, self.refresh_cloud_live)
        self.set_interval(0.12, self.redraw)
        self.refresh_state()
        self.refresh_cloud_live()
        self.listen_events()
        self.query_one("#prompt", Input).focus()

    # ── data ────────────────────────────────────────────────────────────

    @work(thread=True, exclusive=True, group="state")
    def refresh_state(self) -> None:
        try:
            r = requests.get(
                f"{self.api}/modules/gpu-deck/state", headers=self.headers,
                timeout=4,
            )
            r.raise_for_status()
            state = r.json()
        except requests.RequestException as e:
            state = {"error": str(e)}
        self.call_from_thread(self._set_state, state)

    def _set_state(self, state: dict) -> None:
        self.state = state

    @work(thread=True, exclusive=True, group="cloud-live")
    def refresh_cloud_live(self) -> None:
        """Fast poll: is the cloud orchestrator thinking right now."""
        try:
            r = requests.get(
                f"{self.api}/modules/gpu-deck/cloud-live",
                headers=self.headers,
                timeout=3,
            )
            r.raise_for_status()
            live = r.json().get("inFlight", [])
        except requests.RequestException:
            live = None
        self.call_from_thread(self._set_cloud_live, live)

    def _set_cloud_live(self, live: list | None) -> None:
        self.cloud_live = live

    @work(group="ws")
    async def listen_events(self) -> None:
        """Push events from WS /ws/events; reconnects with backoff."""
        import websockets

        url = (
            self.api.replace("http://", "ws://")
            + f"/ws/events?token={self.token}"
        )
        while True:
            try:
                async with websockets.connect(url) as ws:
                    self._log_line(Text("bus ● live", style=GREEN))
                    async for frame in ws:
                        try:
                            self._on_bus_event(json.loads(frame))
                        except ValueError:
                            pass
            except Exception:
                self._log_line(Text("bus ○ down — retrying…", style="dim"))
                await asyncio.sleep(3)

    def _tag(self, task_id: str) -> Text:
        color = self.TAG_COLORS[hash(task_id) % len(self.TAG_COLORS)]
        return Text(f"[{task_id[-10:]}] ", style=f"bold {color}")

    def _on_bus_event(self, e: dict) -> None:
        tid = e.get("taskId")
        if e.get("type") == "task_start" and tid:
            # Esc targets the most recently started task
            self.active_task = tid
            self._show_transcript(True)
        if tid:
            # multiplexed: every agent's events stream in, tagged per task
            self._append_event(e, self._tag(tid))
        if e.get("type") == "task_done":
            if tid == self.active_task:
                self.active_task = None
            self.refresh_state()

    # ── transcript pane ─────────────────────────────────────────────────

    def _show_transcript(self, visible: bool) -> None:
        self.query_one("#transcript", RichLog).styles.display = (
            "block" if visible else "none"
        )

    def _log_line(self, text: Text) -> None:
        self.transcript_lines.append(text.plain)
        del self.transcript_lines[:-500]
        log = self.query_one("#transcript", RichLog)
        if log.styles.display == "none":
            self._show_transcript(True)
        log.write(text)

    def _append_event(self, e: dict, tag: Text | None = None) -> None:
        t = e["type"]
        if t == "log":
            style = RED if e.get("level") == "error" else "#cfe8f5"
            body = Text(e.get("line", ""), style=style)
        elif t == "task_start":
            body = Text(f"▶ {e.get('title', '')}", style=GREEN)
        elif t == "task_done":
            body = Text(f"■ done — {e.get('status')}", style=GREEN)
        elif t == "file_diff":
            body = Text(f"⇄ diff {e.get('path')}", style=CYAN)
        else:
            return
        if tag is not None:
            line = tag.copy()
            line.append_text(body)
        else:
            line = body
        self._log_line(line)

    # ── slash-command palette ───────────────────────────────────────────

    @property
    def menu_open(self) -> bool:
        return bool(self.menu_items)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "prompt":
            return
        value = event.value
        if value.startswith("/") and " " not in value:
            token = value.split()[0] if value.strip() else "/"
            self.menu_items = [
                c for c in self.COMMANDS if c[0].startswith(token)
            ]
            self.menu_idx = min(self.menu_idx, max(len(self.menu_items) - 1, 0))
        else:
            self.menu_items = []
            self.menu_idx = 0
        self._render_menu()

    def _render_menu(self) -> None:
        menu = self.query_one("#cmdmenu", Static)
        if not self.menu_open:
            menu.styles.display = "none"
            return
        out = Text()
        for i, (cmd, usage, desc) in enumerate(self.menu_items):
            sel = i == self.menu_idx
            out.append("❯ " if sel else "  ", style=f"bold {CYAN}")
            out.append(f"{usage:<24}", style=f"bold {CYAN}" if sel else CYAN)
            out.append(f" {desc}\n", style="#cfe8f5" if sel else "dim")
        out.append("  ↑↓ choose · tab/enter complete · esc close", style="dim")
        menu.update(out)
        menu.styles.display = "block"

    def _menu_complete(self) -> None:
        cmd, usage, _ = self.menu_items[self.menu_idx]
        prompt = self.query_one("#prompt", Input)
        needs_args = "<" in usage
        prompt.value = cmd + (" " if needs_args else "")
        prompt.cursor_position = len(prompt.value)
        if not needs_args:
            self.menu_items = []
            self._render_menu()

    def action_menu_tab(self) -> None:
        if self.menu_open:
            self._menu_complete()
        elif not isinstance(self.screen, TaskScreen):
            self.screen.focus_next()

    def show_help(self) -> None:
        self._log_line(Text("COMMANDS:", style=f"bold {AMBER}"))
        for _, usage, desc in self.COMMANDS:
            line = Text("  ")
            line.append(f"{usage:<24}", style=CYAN)
            line.append(f" {desc}")
            self._log_line(line)
        self._log_line(
            Text("  bare text (no /)        quick question → local model "
                 "router", style="dim")
        )
        self._log_line(
            Text("  keys: ↑↓ select · → drill · j/k scroll · F1/F2 workers · "
                 "esc cancel/close · ^o plane · ^q quit", style="dim")
        )

    # ── command deck ────────────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        line = event.value.strip()
        # Enter with the palette open completes instead of submitting,
        # unless the token already IS the highlighted no-arg command
        if self.menu_open:
            cmd, usage, _ = self.menu_items[self.menu_idx]
            if line != cmd or "<" in usage:
                self._menu_complete()
                return
            self.menu_items = []
            self._render_menu()
        event.input.value = ""
        if not line:
            # k9s-style: Enter on an empty prompt drills into the selection
            self.action_drill()
            return
        if line == "/help":
            self.show_help()
            return
        hermes_bin = str(Path.home() / ".hermes/hermes-agent/venv/bin/hermes")
        if line in ("/quit", "/q"):
            self.exit()
        elif line == "/cancel":
            self.action_cancel_task()
        elif line.startswith("/run "):
            self._dispatch_run(shlex.split(line[5:]), title=line[5:][:60])
        elif line.startswith("/hermes! "):
            # full profile: all toolsets + rules/memory (~12.5k tok overhead)
            prompt = line[9:]
            self._dispatch_run(
                [hermes_bin, "-z", prompt],
                title=f"hermes!: {prompt[:50]}",
                worker="hermes",
            )
        elif line.startswith("/hermes "):
            # slim profile: no rules/memory injection, web toolset only —
            # cuts the fixed prompt overhead for quick chats
            prompt = line[8:]
            self._dispatch_run(
                [hermes_bin, "--ignore-rules", "-t", "web", "-z", prompt],
                title=f"hermes: {prompt[:50]}",
                worker="hermes",
            )
        elif line.startswith("/ask "):
            self.ask_router(line[5:])
        elif line == "/reset-cloud":
            self.reset_cloud()
        elif line == "/models":
            self.list_models()
        elif line.startswith("/model "):
            self.switch_model(line[7:].strip())
        elif line == "/reset-ledger":
            self.reset_ledger()
        elif line == "/clear":
            self.query_one("#transcript", RichLog).clear()
            self.transcript_lines.clear()
            self._show_transcript(False)
        elif line.startswith("/"):
            self._log_line(Text(f"unknown command: {line}", style=RED))
        else:
            # bare text = quick question → LOCAL model router (free tokens);
            # cloud kimi is reserved for /hermes orchestration
            self.ask_router(line)

    @work(thread=True, group="dispatch")
    def _dispatch_run(self, cmd: list[str], title: str, worker: str = "operator") -> None:
        try:
            r = requests.post(
                f"{self.api}/modules/task-runner/run",
                headers=self.headers,
                json={"cmd": cmd, "title": title, "worker": worker},
                timeout=10,
            )
            r.raise_for_status()
            tid = r.json()["taskId"]
            self.call_from_thread(self._set_active, tid)
        except requests.RequestException as e:
            self.call_from_thread(
                self._log_line, Text(f"dispatch failed: {e}", style=RED)
            )

    def _set_active(self, task_id: str) -> None:
        self.active_task = task_id
        self._show_transcript(True)

    @work(thread=True, group="dispatch")
    def ask_router(self, prompt: str) -> None:
        """/ask — one-shot to the model router (local lane, paid fallback)."""
        self.call_from_thread(
            self._log_line, Text(f"? {prompt}", style=AMBER)
        )
        try:
            r = requests.post(
                f"{self.api}/llm/complete",
                headers=self.headers,
                json={"messages": [{"role": "user", "content": prompt}],
                      "difficulty": "easy", "max_tokens": 1024},
                timeout=180,
            )
            r.raise_for_status()
            d = r.json()
            reply = Text()
            reply.append(f"[{d['lane']}] ", style=CYAN)
            reply.append(d["content"].strip())
            self.call_from_thread(self._log_line, reply)
        except requests.RequestException as e:
            self.call_from_thread(
                self._log_line, Text(f"ask failed: {e}", style=RED)
            )

    @work(thread=True, group="dispatch")
    def reset_cloud(self) -> None:
        """/reset-cloud — zero the cloud-orchestrator token window."""
        try:
            r = requests.post(
                f"{self.api}/modules/gpu-deck/cloud-reset",
                headers=self.headers,
                timeout=10,
            )
            r.raise_for_status()
            n = r.json().get("cleared", 0)
            self.call_from_thread(
                self._log_line,
                Text(f"cloud window reset — {n} records archived", style=AMBER),
            )
        except requests.RequestException as e:
            self.call_from_thread(
                self._log_line, Text(f"reset failed: {e}", style=RED)
            )
        self.refresh_state()

    @work(thread=True, group="dispatch")
    def list_models(self) -> None:
        """/models — catalog of local GGUFs usable by the workers."""
        try:
            r = requests.get(
                f"{self.api}/modules/gpu-deck/models",
                headers=self.headers,
                timeout=15,
            )
            r.raise_for_status()
            self.model_catalog = r.json()["models"]
        except requests.RequestException as e:
            self.call_from_thread(
                self._log_line, Text(f"models failed: {e}", style=RED)
            )
            return

        def show() -> None:
            self._log_line(Text("MODELS (local GGUFs):", style=f"bold {AMBER}"))
            for i, m in enumerate(self.model_catalog):
                mark = "  " if m["loadable"] else "✗ "
                style = "#cfe8f5" if m["loadable"] else "dim"
                note = "" if m["loadable"] else " (arch unsupported by llama.cpp)"
                self._log_line(
                    Text(
                        f" {mark}[{i}] {m['name']} · {m['sizeGB']}GB · "
                        f"{m['arch']}{note}",
                        style=style,
                    )
                )
            self._log_line(
                Text("   switch: /model <n>  or  /model <gpu> <n>   "
                     "(gpus: r9700, 7900xtx)", style="dim")
            )

        self.call_from_thread(show)

    @work(thread=True, group="dispatch")
    def switch_model(self, arg: str) -> None:
        """/model <n> or /model <gpu> <n> — set a card's worker model."""
        catalog = getattr(self, "model_catalog", None)
        if not catalog:
            self.call_from_thread(
                self._log_line, Text("run /models first", style=RED)
            )
            return
        tokens = arg.split()
        gpu = "r9700"
        if len(tokens) == 2:
            gpu, sel = tokens
        else:
            sel = tokens[0] if tokens else ""
        known_gpus = {w["gpu"] for w in self.state.get("workers", [])}
        if gpu not in known_gpus:
            self.call_from_thread(
                self._log_line,
                Text(f"unknown gpu '{gpu}' — one of: {', '.join(sorted(known_gpus))}",
                     style=RED),
            )
            return
        installed = {g["id"] for g in self.state.get("gpus", [])}
        if gpu not in installed:
            self.call_from_thread(
                self._log_line,
                Text(f"{gpu} isn't installed yet — selection will apply when "
                     "the card lands", style=AMBER),
            )
        try:
            m = catalog[int(sel)]
        except (ValueError, IndexError):
            m = next((x for x in catalog if x["name"] == sel), None)
        if m is None:
            self.call_from_thread(
                self._log_line, Text(f"unknown model: {sel}", style=RED)
            )
            return
        if not m["loadable"]:
            self.call_from_thread(
                self._log_line,
                Text(f"{m['name']} uses arch '{m['arch']}' — llama.cpp can't "
                     "load it", style=RED),
            )
            return
        self.call_from_thread(
            self._log_line,
            Text(f"switching {gpu} → {m['name']} ({m['sizeGB']}GB, loads in "
                 "~10-40s)…", style=AMBER),
        )
        try:
            r = requests.post(
                f"{self.api}/modules/gpu-deck/workers/vault-worker-{gpu}/model",
                headers=self.headers,
                json={"path": m["path"], "alias": m["name"]},
                timeout=30,
            )
            r.raise_for_status()
            self.call_from_thread(
                self._log_line,
                Text(f"worker restarting with {m['name']} — watch the deck",
                     style=GREEN),
            )
        except requests.RequestException as e:
            self.call_from_thread(
                self._log_line, Text(f"switch failed: {e}", style=RED)
            )
        self.refresh_state()

    @work(thread=True, group="dispatch")
    def reset_ledger(self) -> None:
        """/reset-ledger — zero the local/paid router token counters."""
        try:
            r = requests.post(
                f"{self.api}/llm/ledger/reset", headers=self.headers, timeout=10
            )
            r.raise_for_status()
            prev = r.json().get("previous", {})
            self.call_from_thread(
                self._log_line,
                Text(
                    f"ledger reset — was local {prev.get('localTokens', 0)} / "
                    f"paid {prev.get('paidTokens', 0)} tok",
                    style=AMBER,
                ),
            )
        except requests.RequestException as e:
            self.call_from_thread(
                self._log_line, Text(f"reset failed: {e}", style=RED)
            )
        self.refresh_state()

    def action_cancel_task(self) -> None:
        """Esc, layered: close the palette → cancel a running task → dismiss
        the transcript pane → refocus the prompt (never a dead key)."""
        prompt = self.query_one("#prompt", Input)
        if self.menu_open or prompt.value:
            self.menu_items = []
            self._render_menu()
            prompt.value = ""
            return
        if self.active_task:
            tid = self.active_task
            self._log_line(Text(f"✋ cancelling {tid}…", style=AMBER))
            self._cancel(tid)
            return
        transcript = self.query_one("#transcript", RichLog)
        if transcript.styles.display != "none":
            self._show_transcript(False)
        self.query_one("#prompt", Input).focus()

    def on_key(self, event) -> None:
        """Typing anywhere on the main screen lands in the prompt — focus can
        never get stuck on the transcript/footer."""
        if isinstance(self.screen, TaskScreen):
            return
        prompt = self.query_one("#prompt", Input)
        ch = getattr(event, "character", None)
        if ch and ch.isprintable() and not prompt.has_focus:
            prompt.focus()
            prompt.insert_text_at_cursor(ch)
            event.stop()

    @work(thread=True, group="dispatch")
    def _cancel(self, task_id: str) -> None:
        try:
            requests.post(
                f"{self.api}/modules/task-runner/cancel/{task_id}",
                headers=self.headers,
                timeout=10,
            )
        except requests.RequestException:
            pass

    # ── selection / drill-down / controls ───────────────────────────────

    def _tasks(self) -> list[dict]:
        return list(self.state.get("runningTasks", [])) + list(
            self.state.get("history", [])
        )

    def action_move(self, delta: int) -> None:
        # palette open → arrows navigate the menu
        if self.menu_open:
            self.menu_idx = (self.menu_idx + delta) % len(self.menu_items)
            self._render_menu()
            return
        # priority bindings are app-global: delegate to the drill screen
        if isinstance(self.screen, TaskScreen):
            self.screen.action_nav(delta)
            return
        n = len(self._tasks())
        if n:
            self.cursor = (self.cursor + delta) % n

    def action_drill(self) -> None:
        tasks = self._tasks()
        if tasks:
            self.push_screen(
                TaskScreen([t["taskId"] for t in tasks], self.cursor % len(tasks))
            )

    def action_drill_right(self) -> None:
        """→ drills — unless you're editing prompt text, where it stays a
        cursor key (priority binding steals it, so re-dispatch manually)."""
        if isinstance(self.screen, TaskScreen):
            self.screen.action_go_right()
            return
        prompt = self.query_one("#prompt", Input)
        if prompt.has_focus and prompt.value:
            prompt.action_cursor_right()
        else:
            self.action_drill()

    def action_toggle_worker(self, idx: int) -> None:
        workers = self.state.get("workers", [])
        if idx >= len(workers):
            return
        w = workers[idx]
        gpus = {g["id"] for g in self.state.get("gpus", [])}
        if w["gpu"] not in gpus:
            self._log_line(
                Text(
                    f"{w['gpu']} isn't installed yet — F{idx + 1} activates "
                    "when the card lands",
                    style=AMBER,
                )
            )
            return
        action = "stop" if w.get("up") else "start"
        self._toggle_worker(w["unit"], action)

    @work(thread=True, group="dispatch")
    def _toggle_worker(self, unit: str, action: str) -> None:
        try:
            r = requests.post(
                f"{self.api}/modules/gpu-deck/workers/{unit}/{action}",
                headers=self.headers,
                timeout=15,
            )
            r.raise_for_status()
            msg, style = f"{unit}: {action} ok", GREEN
        except requests.RequestException as e:
            msg, style = f"{unit}: {action} failed — {e}", RED
        self.call_from_thread(self._log_line, Text(msg, style=style))
        self.refresh_state()

    def action_open_issue(self) -> None:
        for t in self.state.get("runningTasks", []) + self.state.get("history", []):
            url = t.get("plane", {}).get("url")
            if url:
                webbrowser.open(url)
                return

    # ── deck redraw ─────────────────────────────────────────────────────

    def _redraw_orchline(self) -> None:
        line = Text()
        live = self.cloud_live
        if live is None:
            line.append("ORCHESTRATOR ", style=f"bold {AMBER}")
            line.append("? relay unreachable", style="dim")
        elif live:
            spin = SPIN[self.tick % len(SPIN)]
            line.append("ORCHESTRATOR ", style=f"bold {AMBER}")
            line.append(f"{spin} thinking ", style=f"bold {MAGENTA}")
            line.append(
                " · ".join(
                    f"{e.get('model')} {e.get('elapsedS', 0):.0f}s" for e in live
                ),
                style=CYAN,
            )
        else:
            line.append("ORCHESTRATOR ", style=f"bold {AMBER}")
            line.append("○ idle", style="dim")
        self.query_one("#orchline", Static).update(line)

    def redraw(self) -> None:
        self.tick += 1
        self._redraw_orchline()
        s = self.state
        out = Text()
        out.append("VAULT · GPU DECK\n", style=f"bold {AMBER}")
        if s.get("error"):
            out.append(f"  {s['error']}\n", style=RED)
            self.query_one("#deck", Static).update(out)
            return
        led = s.get("ledger", {})
        out.append(
            f"  local {led.get('localTokens', 0)} tok · paid "
            f"{led.get('paidTokens', 0)} tok\n\n",
            style="dim",
        )
        workers = {w["gpu"]: w for w in s.get("workers", [])}
        # F-key number = position in the workers list (stable), not GPU order
        fkey = {w["gpu"]: i + 1 for i, w in enumerate(s.get("workers", []))}
        throughput = s.get("throughput", {})
        for g in s.get("gpus", []):
            used, total = g["vramUsedGB"], g["vramTotalGB"]
            bar = "█" * int(20 * used / max(total, 1)) + "░" * (
                20 - int(20 * used / max(total, 1))
            )
            out.append(f"◉ {g['name']} ", style=f"bold {CYAN}")
            out.append(f"{bar} {used}/{total} GB\n", style="#7ddcff")
            tp = throughput.get(g["id"])
            if tp:
                out.append(
                    f"  ⚡ {tp['liveTps']} tok/s · 1h Ø {tp['hourAvgTps']} "
                    f"tok/s · {tp['hourTokens']:,} tok\n",
                    style=GREEN,
                )
            w = workers.get(g["id"])
            if w:
                if w.get("up"):
                    out.append(f"  ├─ [F{fkey[g['id']]}] vault-worker ", style=GREEN)
                    out.append("● ", style=GREEN)
                    out.append(
                        f"{w.get('model')}", style=f"bold {MAGENTA}"
                    )
                    out.append(
                        f" · {w.get('activeSlots', 0)} slot(s)\n", style=GREEN
                    )
                else:
                    out.append(f"  ├─ [F{fkey[g['id']]}] vault-worker ○ down", style="dim")
                    out.append("  ⭘ next: ", style="dim")
                    out.append(
                        f"{w.get('selectedModel', '?')}\n",
                        style=MAGENTA,
                    )
            else:
                out.append(
                    "  └─ no vault worker (display / ollama card)\n",
                    style="dim",
                )
        for m in s.get("ollama", []):
            out.append(
                f"  ollama · {m['model']} · {m['vramGB']}GB vram\n",
                style="#cfe8f5",
            )
        out.append("\nCLOUD ORCHESTRATOR · ollama.com\n", style=f"bold {AMBER}")
        cloud = s.get("cloud", [])
        if not cloud:
            out.append("  no traffic in the last hour\n", style="dim")
        for c in cloud:
            spin = SPIN[self.tick % len(SPIN)] if c.get("inFlight") else "├─"
            approx = "≈" if c.get("approx") else ""
            out.append(f"  {spin} {c['model']} ", style="bold")
            out.append(
                f"{c['requests']} req · in {c['tokensIn']:,} / out "
                f"{c['tokensOut']:,}{approx} tok · {c['avgTps']} tok/s · "
                f"{c['avgLatencyMs']}ms\n",
                style="dim",
            )
        out.append("\nRUNNING\n", style=f"bold {AMBER}")
        running = s.get("runningTasks", [])
        if not running:
            out.append("  idle\n", style="dim")
        tasks = self._tasks()
        for idx, t in enumerate(running):
            spin = SPIN[self.tick % len(SPIN)]
            age = int(time.time() - t.get("startedAt", time.time()))
            sel = "▸" if tasks and idx == self.cursor else " "
            out.append(
                f" {sel}{spin} {t['taskId']} {t.get('title', '')} "
                f"[{t.get('difficulty')} · {t.get('worker')} · {age}s]\n"
            )
            p = t.get("plane", {})
            if p.get("linked"):
                out.append(
                    f"    {p.get('project')} › {p.get('milestone')} › "
                    f"{p.get('issue')}\n",
                    style=MAGENTA,
                )
            else:
                out.append(f"    {p.get('reason', 'unplanned')}\n", style="dim")
        out.append("\nHISTORY\n", style=f"bold {AMBER}")
        for j, h in enumerate(s.get("history", [])):
            idx = len(running) + j
            mark = "✓" if h.get("status") == "success" else "✗"
            style = GREEN if h.get("status") == "success" else RED
            sel = "▸" if tasks and idx == self.cursor else " "
            out.append(f" {sel}{mark} ", style=style)
            out.append(
                f"{h['taskId']} {h.get('title', '')} {h.get('durationS', '?')}s\n"
            )
        self.query_one("#deck", Static).update(out)


if __name__ == "__main__":
    VaultTop().run()
