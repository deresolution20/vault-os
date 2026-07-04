#!/usr/bin/env python3
"""vault-top — terminal TUI for the VAULT GPU deck (same data as the window).

Run: tools/vault-top   (wrapper: uv run --with textual --with requests ...)
Keys: q quit · 1/2 start-stop worker · o open selected task in Plane
      ↑/↓ select task · enter drill down · esc back
"""

from __future__ import annotations

import time
import webbrowser
from pathlib import Path

import requests
from rich.text import Text
from textual.app import App, ComposeResult
from textual.screen import Screen
from textual.widgets import Footer, Static

ROOT = Path(__file__).resolve().parents[1]
SPIN = "⠋⠙⠹⠸⠼⠴⠦⠧"


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
            out.append(d["error"], style="#ff5f56")
            self.query_one("#detail", Static).update(out)
            return
        info = d.get("info", {})
        mark = "▶" if d.get("running") else (
            "✓" if info.get("status") == "success" else "·"
        )
        out.append(
            f"{mark} {info.get('taskId')} {info.get('title', '')}\n",
            style="bold #ffb347",
        )
        p = d.get("plane", {})
        if p.get("linked"):
            out.append(
                f"  {p.get('project')} › {p.get('milestone')} › {p.get('issue')}\n\n",
                style="#ff2bd6",
            )
        else:
            out.append(f"  {p.get('reason', 'unplanned')}\n\n", style="dim")
        events = d.get("events", [])
        out.append(f"TRANSCRIPT · {len(events)} events\n", style="bold #ffb347")
        for e in events[-40:]:
            stamp = time.strftime("%H:%M:%S", time.localtime(e.get("ts", 0)))
            out.append(f"  {stamp} ", style="dim")
            if e["type"] == "log":
                style = "#ff5f56" if e.get("level") == "error" else "#cfe8f5"
                out.append(f"{e.get('line', '')}\n", style=style)
            elif e["type"] == "file_diff":
                out.append(f"⇄ diff {e.get('path')}\n", style="#00e5ff")
            elif e["type"] == "task_start":
                out.append("▶ task started\n", style="#7ddc8a")
            elif e["type"] == "task_done":
                out.append(f"■ done — {e.get('status')}\n", style="#7ddc8a")
            else:
                out.append(f"{e['type']}\n")
        self.query_one("#detail", Static).update(out)


class VaultTop(App):
    BINDINGS = [
        ("q", "quit", "quit"),
        ("1", "toggle_worker(0)", "worker 1"),
        ("2", "toggle_worker(1)", "worker 2"),
        ("o", "open_issue", "open in Plane"),
        ("up", "move(-1)", "select ↑"),
        ("down", "move(1)", "select ↓"),
        ("enter", "drill", "drill down"),
    ]
    CSS = "Screen {background: #04060c;} Static {padding: 1 2;}"

    def __init__(self) -> None:
        super().__init__()
        env = _env()
        self.api = f"http://127.0.0.1:{env.get('HERMES_API_PORT', '8100')}"
        self.headers = {"Authorization": f"Bearer {env.get('HERMES_API_TOKEN', '')}"}
        self.state: dict = {}
        self.tick = 0
        self.cursor = 0

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
        if tasks:
            self.push_screen(TaskScreen(tasks[self.cursor]["taskId"]))

    def compose(self) -> ComposeResult:
        yield Static(id="deck")
        yield Footer()

    def on_mount(self) -> None:
        self.set_interval(2.0, self.refresh_state)
        self.set_interval(0.12, self.redraw)
        self.refresh_state()

    def refresh_state(self) -> None:
        try:
            r = requests.get(
                f"{self.api}/modules/gpu-deck/state", headers=self.headers, timeout=4
            )
            r.raise_for_status()
            self.state = r.json()
        except requests.RequestException as e:
            self.state = {"error": str(e)}

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
        for t in self.state.get("runningTasks", []):
            url = t.get("plane", {}).get("url")
            if url:
                webbrowser.open(url)
                return

    def redraw(self) -> None:
        self.tick += 1
        s = self.state
        out = Text()
        out.append("VAULT · GPU DECK\n", style="bold #ffb347")
        if s.get("error"):
            out.append(f"  {s['error']}\n", style="#ff5f56")
            self.query_one("#deck", Static).update(out)
            return
        led = s.get("ledger", {})
        out.append(
            f"  local {led.get('localTokens', 0)} tok · paid "
            f"{led.get('paidTokens', 0)} tok\n\n",
            style="dim",
        )
        workers = {w["gpu"]: w for w in s.get("workers", [])}
        for i, g in enumerate(s.get("gpus", [])):
            used, total = g["vramUsedGB"], g["vramTotalGB"]
            bar = "█" * int(20 * used / max(total, 1)) + "░" * (
                20 - int(20 * used / max(total, 1))
            )
            out.append(f"◉ {g['name']} ", style="bold #00e5ff")
            out.append(f"{bar} {used}/{total} GB\n", style="#7ddcff")
            w = workers.get(g["id"])
            if w:
                if w.get("up"):
                    out.append(
                        f"  ├─ [{i + 1}] vault-worker ● {w.get('model')} · "
                        f"{w.get('activeSlots', 0)} slot(s)\n",
                        style="#7ddc8a",
                    )
                else:
                    out.append(f"  ├─ [{i + 1}] vault-worker ○ down\n", style="dim")
        for m in s.get("ollama", []):
            out.append(
                f"  ollama · {m['model']} · {m['vramGB']}GB vram\n", style="#cfe8f5"
            )
        out.append("\nRUNNING\n", style="bold #ffb347")
        running = s.get("runningTasks", [])
        if not running:
            out.append("  idle\n", style="dim")
        for t in running:
            spin = SPIN[self.tick % len(SPIN)]
            age = int(time.time() - t.get("startedAt", time.time()))
            out.append(
                f"  {spin} {t['taskId']} {t.get('title', '')} "
                f"[{t.get('difficulty')} · {t.get('worker')} · {age}s]\n"
            )
            p = t.get("plane", {})
            if p.get("linked"):
                out.append(
                    f"    {p.get('project')} › {p.get('milestone')} › "
                    f"{p.get('issue')}\n",
                    style="#ff2bd6",
                )
            else:
                out.append(f"    {p.get('reason', 'unplanned')}\n", style="dim")
        out.append("\nHISTORY\n", style="bold #ffb347")
        for h in s.get("history", []):
            mark = "✓" if h.get("status") == "success" else "✗"
            style = "#7ddc8a" if h.get("status") == "success" else "#ff5f56"
            out.append(f"  {mark} ", style=style)
            out.append(f"{h['taskId']} {h.get('title', '')} {h.get('durationS', '?')}s\n")
        self.query_one("#deck", Static).update(out)


if __name__ == "__main__":
    VaultTop().run()
