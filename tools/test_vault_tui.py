#!/usr/bin/env python3
"""Headless e2e for the vault TUI: dispatch /run via the prompt, verify the
transcript streams and the task completes. Needs the Hermes API on :8100.

Run: uv run --with textual --with requests --with websockets \
       python3 tools/test_vault_tui.py
"""

import asyncio
import sys

from textual.widgets import Input, RichLog

from vault_top import VaultTop


async def main() -> int:
    app = VaultTop()
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause(1.0)

        # deck state must have loaded (GPUs present)
        assert app.state.get("gpus"), f"no deck state: {app.state}"
        print("✓ deck state loaded:", [g["id"] for g in app.state["gpus"]])

        # type a /run command into the prompt and submit
        prompt = app.query_one("#prompt", Input)
        prompt.value = "/run bash -c 'echo tui-e2e-alpha; sleep 1; echo tui-e2e-beta'"
        await pilot.press("enter")

        # wait for dispatch + streaming + completion
        for _ in range(30):
            await pilot.pause(0.5)
            text = "\n".join(app.transcript_lines)
            if "tui-e2e-beta" in text and "done" in text:
                break
        else:
            raise AssertionError(
                "transcript never showed streamed output+done; "
                f"active={app.active_task} lines={app.transcript_lines[-8:]}"
            )
        print("✓ /run dispatched, streamed, completed in transcript")

        # esc-cancel path: start a long task, cancel it
        prompt.value = "/run sleep 30"
        await pilot.press("enter")
        for _ in range(20):
            await pilot.pause(0.5)
            if app.active_task:
                break
        assert app.active_task, "long task never became active"
        tid = app.active_task
        prompt.value = ""
        await pilot.press("escape")
        for _ in range(20):
            await pilot.pause(0.5)
            if app.active_task is None:
                break
        assert app.active_task is None, "cancel did not clear active task"
        print(f"✓ esc-interrupt cancelled {tid}")

        # navigation: arrows move the selection even with the prompt focused
        await pilot.pause(1.0)
        before = app.cursor
        await pilot.press("down")
        assert app.cursor != before or len(app._tasks()) <= 1, "cursor stuck"
        print("✓ arrow selection works with prompt focused")

        # → drills into the Miller view; ↑/↓ move the task selection there
        await pilot.press("right")
        await pilot.pause(0.8)
        from vault_top import TaskScreen

        assert isinstance(app.screen, TaskScreen), f"no drill: {app.screen}"
        drill = app.screen
        print("✓ → drilled into", drill.task_id)
        first = drill.task_id
        if len(drill.task_ids) > 1:
            await pilot.press("down")
            await pilot.pause(0.5)
            assert drill.task_id != first, "↑/↓ didn't move drill selection"
            print("✓ ↑/↓ moves selection inside drill view")

        # second → focuses the output pane; j/k scroll it
        await pilot.press("right")
        assert drill.depth == 2, "→ didn't focus output pane"
        await pilot.press("j")
        await pilot.press("j")
        await pilot.press("k")
        print("✓ →→ focused output; j/k scrolled without error")

        # ← walks back: depth 2 → 1 → pop to deck
        await pilot.press("left")
        assert drill.depth == 1, "← didn't return focus to the list"
        await pilot.press("left")
        await pilot.pause(0.3)
        assert not isinstance(app.screen, TaskScreen), "← didn't pop to deck"
        print("✓ ← ← walked back out to the deck")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
