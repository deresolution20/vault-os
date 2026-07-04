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

        # empty-Enter drills into the selected task; Esc pops back
        await pilot.press("enter")
        await pilot.pause(0.8)
        from vault_top import TaskScreen

        assert isinstance(app.screen, TaskScreen), f"no drill: {app.screen}"
        print("✓ empty-Enter drilled into", app.screen.task_id)
        await pilot.press("escape")
        await pilot.pause(0.3)
        assert not isinstance(app.screen, TaskScreen), "esc didn't pop"
        print("✓ esc popped back to deck")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
