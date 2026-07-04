#!/usr/bin/env python3
"""M6.1 — run a build command and stream its life to the VAULT event bus.

Wraps any shell command: emits task_start, tails stdout/stderr as log events,
snapshots `git diff` of the working tree as file_diff chunks (PRD §11.4),
then task_done with the exit status.

Usage:
  uv run --with requests --with python-dotenv tools/emit_build_events.py \
      --task-id M6.1-demo --title "demo task" --dir <git-worktree> -- <command...>
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

import requests
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "build-agent"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task-id", required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--difficulty", default="easy",
                    choices=["trivial", "easy", "medium", "hard"])
    ap.add_argument("--worker", default="fable-5")
    ap.add_argument("--dir", default=str(ROOT), help="git working tree to diff")
    ap.add_argument("cmd", nargs="+", help="command to run (after --)")
    args = ap.parse_args()

    env = dotenv_values(ROOT / ".env")
    api = f"http://127.0.0.1:{env.get('HERMES_API_PORT') or 8100}"
    s = requests.Session()
    s.headers["Authorization"] = f"Bearer {env.get('HERMES_API_TOKEN', '')}"

    def emit(payload: dict) -> None:
        payload.setdefault("ts", time.time())
        payload.setdefault("source", SOURCE)
        try:
            s.post(f"{api}/events", json=payload, timeout=5).raise_for_status()
        except Exception as e:
            print(f"[emit] {e}", file=sys.stderr)

    emit({"type": "task_start", "taskId": args.task_id, "title": args.title,
          "difficulty": args.difficulty, "worker": args.worker})

    proc = subprocess.Popen(
        args.cmd, cwd=args.dir, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, bufsize=1,
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        line = line.rstrip("\n")
        print(line)
        emit({"type": "log", "taskId": args.task_id, "level": "info",
              "line": line[:500]})
    code = proc.wait()

    diff = subprocess.run(
        ["git", "diff"], cwd=args.dir, capture_output=True, text=True
    ).stdout
    if diff:
        # first changed file as the headline; panel tails the chunk
        first = next((l[6:] for l in diff.splitlines() if l.startswith("+++ b/")),
                     "worktree")
        emit({"type": "file_diff", "taskId": args.task_id, "path": first,
              "diff": diff[-4000:]})

    emit({"type": "task_done", "taskId": args.task_id,
          "status": "success" if code == 0 else "failure"})
    return code


if __name__ == "__main__":
    sys.exit(main())
