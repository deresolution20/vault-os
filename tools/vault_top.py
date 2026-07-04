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
from textual.containers import Vertical
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
    """Drill-down: one task's transcript, polled live."""

    BINDINGS = [("escape", "app.pop_screen", "back"), ("q", "app.quit", "quit")]

    def __init__(self, task_id: str) -> None:
        super().__init__()
        self.task_id = task_id
        self.detail: dict = {}

    def compose(self) -> ComposeResult:
        yield Static(id="detail")
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(2.0, self.refresh_detail)
        self.refresh_detail()

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
        d = self.detail
        out = Text()
        if d.get("error"):
            out.append(d["error"], style=RED)
            self.query_one("#detail", Static).update(out)
            return
        info = d.get("info", {})
        mark = "▶" if d.get("running") else (
            "✓" if info.get("status") == "success" else "·"
        )
        out.append(
            f"{mark} {info.get('taskId')} {info.get('title', '')}\n",
            style=f"bold {AMBER}",
        )
        p = d.get("plane", {})
        if p.get("linked"):
            out.append(
                f"  {p.get('project')} › {p.get('milestone')} › {p.get('issue')}\n\n",
                style=MAGENTA,
            )
        else:
            out.append(f"  {p.get('reason', 'unplanned')}\n\n", style="dim")
        events = d.get("events", [])
        out.append(f"TRANSCRIPT · {len(events)} events\n", style=f"bold {AMBER}")
        for e in events[-40:]:
            stamp = time.strftime("%H:%M:%S", time.localtime(e.get("ts", 0)))
            out.append(f"  {stamp} ", style="dim")
            if e["type"] == "log":
                style = RED if e.get("level") == "error" else "#cfe8f5"
                out.append(f"{e.get('line', '')}\n", style=style)
            elif e["type"] == "file_diff":
                out.append(f"⇄ diff {e.get('path')}\n", style=CYAN)
            elif e["type"] == "task_start":
                out.append("▶ task started\n", style=GREEN)
            elif e["type"] == "task_done":
                out.append(f"■ done — {e.get('status')}\n", style=GREEN)
            else:
                out.append(f"{e['type']}\n")
        self.query_one("#detail", Static).update(out)


class VaultTop(App):
    TITLE = "VAULT"
    BINDINGS = [
        ("ctrl+q", "quit", "quit"),
        ("escape", "cancel_task", "cancel task"),
        ("f1", "toggle_worker(0)", "worker 1"),
        ("f2", "toggle_worker(1)", "worker 2"),
        ("o", "open_issue", "open in Plane"),
        ("up", "move(-1)", "select ↑"),
        ("down", "move(1)", "select ↓"),
        ("enter", "drill", "drill down"),
    ]
    CSS = f"""
    Screen {{ background: #04060c; }}
    #deck {{ padding: 1 2; height: 1fr; }}
    #transcript {{
        height: 12; border-top: solid {CYAN} 30%;
        background: #04060c; color: #cfe8f5; padding: 0 2; display: none;
    }}
    #prompt {{
        dock: bottom; border: solid {CYAN} 40%;
        background: #060a12; color: {AMBER};
    }}
    """

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
        # plain-text mirror of the transcript (drives tests + future export)
        self.transcript_lines: list[str] = []

    # ── layout ──────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Vertical(
            Static(id="deck"),
            RichLog(id="transcript", markup=False, wrap=True, max_lines=500),
        )
        yield Input(
            placeholder="›  /run <cmd> · /hermes <prompt> · /ask <prompt> · "
            "/cancel · Tab to navigate",
            id="prompt",
        )
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(5.0, self.refresh_state)
        self.set_interval(0.12, self.redraw)
        self.refresh_state()
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

    def _on_bus_event(self, e: dict) -> None:
        tid = e.get("taskId")
        if e.get("type") == "task_start" and tid:
            # follow whatever starts if nothing is active
            if self.active_task is None:
                self.active_task = tid
                self._show_transcript(True)
        if tid and tid == self.active_task:
            self._append_event(e)
        if e.get("type") == "task_done" and tid == self.active_task:
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

    def _append_event(self, e: dict) -> None:
        t = e["type"]
        if t == "log":
            style = RED if e.get("level") == "error" else "#cfe8f5"
            self._log_line(Text(e.get("line", ""), style=style))
        elif t == "task_start":
            self._log_line(
                Text(f"▶ {e.get('taskId')} {e.get('title', '')}", style=GREEN)
            )
        elif t == "task_done":
            self._log_line(Text(f"■ done — {e.get('status')}", style=GREEN))
        elif t == "file_diff":
            self._log_line(Text(f"⇄ diff {e.get('path')}", style=CYAN))

    # ── command deck ────────────────────────────────────────────────────

    def on_input_submitted(self, event: Input.Submitted) -> None:
        line = event.value.strip()
        event.input.value = ""
        if not line:
            return
        if line in ("/quit", "/q"):
            self.exit()
        elif line == "/cancel":
            self.action_cancel_task()
        elif line.startswith("/run "):
            self._dispatch_run(shlex.split(line[5:]), title=line[5:][:60])
        elif line.startswith("/hermes "):
            prompt = line[8:]
            self._dispatch_run(
                [str(Path.home() / ".hermes/hermes-agent/venv/bin/hermes"),
                 "-z", prompt],
                title=f"hermes: {prompt[:50]}",
                worker="hermes",
            )
        elif line.startswith("/ask "):
            self.ask_router(line[5:])
        elif line.startswith("/"):
            self._log_line(Text(f"unknown command: {line}", style=RED))
        else:
            # bare text talks to the orchestrator, Claude Code style
            self._dispatch_run(
                [str(Path.home() / ".hermes/hermes-agent/venv/bin/hermes"),
                 "-z", line],
                title=f"hermes: {line[:50]}",
                worker="hermes",
            )

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

    def action_cancel_task(self) -> None:
        if not self.active_task:
            return
        tid = self.active_task
        self._log_line(Text(f"✋ cancelling {tid}…", style=AMBER))
        self._cancel(tid)

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
        n = len(self._tasks())
        if n:
            self.cursor = (self.cursor + delta) % n

    def action_drill(self) -> None:
        tasks = self._tasks()
        if tasks and not self.query_one("#prompt", Input).has_focus:
            self.push_screen(TaskScreen(tasks[self.cursor]["taskId"]))

    def action_toggle_worker(self, idx: int) -> None:
        workers = self.state.get("workers", [])
        if idx >= len(workers):
            return
        w = workers[idx]
        action = "stop" if w.get("up") else "start"
        try:
            requests.post(
                f"{self.api}/modules/gpu-deck/workers/{w['unit']}/{action}",
                headers=self.headers,
                timeout=10,
            )
        except requests.RequestException:
            pass
        self.refresh_state()

    def action_open_issue(self) -> None:
        for t in self.state.get("runningTasks", []) + self.state.get("history", []):
            url = t.get("plane", {}).get("url")
            if url:
                webbrowser.open(url)
                return

    # ── deck redraw ─────────────────────────────────────────────────────

    def redraw(self) -> None:
        self.tick += 1
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
        throughput = s.get("throughput", {})
        for i, g in enumerate(s.get("gpus", [])):
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
                    out.append(
                        f"  ├─ [F{i + 1}] vault-worker ● {w.get('model')} · "
                        f"{w.get('activeSlots', 0)} slot(s)\n",
                        style=GREEN,
                    )
                else:
                    out.append(f"  ├─ [F{i + 1}] vault-worker ○ down\n", style="dim")
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
