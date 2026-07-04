#!/usr/bin/env python3
"""Mirror docs/BACKLOG-plane-issues.md into Plane, one issue per PRD task.

Idempotent: skips issues whose name already exists in the target project.
Carries difficulty + module as labels (created on demand).

Usage:
  uv run --with requests --with python-dotenv tools/push_backlog_to_plane.py [--dry-run]

Requires in projects/vault-os/.env:
  PLANE_API_URL        e.g. http://localhost:30080  (base, no trailing /api)
  PLANE_API_TOKEN      per-user token from Plane UI (Settings -> API tokens)
  PLANE_WORKSPACE_SLUG
  PLANE_PROJECT_ID     UUID of the target project
"""

import argparse
import re
import sys
from pathlib import Path

import requests
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
BACKLOG = ROOT / "docs/BACKLOG-plane-issues.md"

ROW_RE = re.compile(
    r"^\|\s*(?P<id>M\d[\w.]*b?)\s*\|\s*(?P<title>[^|]+?)\s*\|\s*(?P<difficulty>\w+)\s*\|"
    r"\s*(?P<state>[^|]+?)\s*\|\s*(?P<deps>[^|]*?)\s*\|\s*(?P<notes>[^|]*?)\s*\|$"
)


def parse_backlog() -> list[dict]:
    rows = []
    for line in BACKLOG.read_text().splitlines():
        if m := ROW_RE.match(line.strip()):
            d = m.groupdict()
            if d["id"].lower() == "id":
                continue
            rows.append(d)
    return rows


def is_done(state: str) -> bool:
    return "done" in state.lower() and "todo" not in state.lower()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    env = dotenv_values(ROOT / ".env")
    base = (env.get("PLANE_API_URL") or "").rstrip("/")
    token = env.get("PLANE_API_TOKEN") or ""
    slug = env.get("PLANE_WORKSPACE_SLUG") or ""
    project = env.get("PLANE_PROJECT_ID") or ""
    missing = [
        k
        for k, v in {
            "PLANE_API_URL": base,
            "PLANE_API_TOKEN": token,
            "PLANE_WORKSPACE_SLUG": slug,
            "PLANE_PROJECT_ID": project,
        }.items()
        if not v
    ]
    if missing:
        print(f"missing in .env: {', '.join(missing)}", file=sys.stderr)
        return 1

    api = f"{base}/api/v1/workspaces/{slug}/projects/{project}"
    s = requests.Session()
    s.headers["X-API-Key"] = token

    rows = parse_backlog()
    print(f"parsed {len(rows)} backlog rows")

    # existing issues (paginated)
    existing: set[str] = set()
    url = f"{api}/issues/"
    while url:
        r = s.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
        results = data.get("results", data if isinstance(data, list) else [])
        existing |= {i["name"] for i in results}
        url = data.get("next_page_url") if isinstance(data, dict) else None

    # labels
    r = s.get(f"{api}/labels/", timeout=15)
    r.raise_for_status()
    lbl = r.json()
    labels = {
        l["name"]: l["id"]
        for l in (lbl.get("results") if isinstance(lbl, dict) else lbl)
    }

    def label_id(name: str) -> str:
        if name not in labels:
            r = s.post(f"{api}/labels/", json={"name": name}, timeout=15)
            r.raise_for_status()
            labels[name] = r.json()["id"]
        return labels[name]

    # project states (map done -> completed group)
    r = s.get(f"{api}/states/", timeout=15)
    r.raise_for_status()
    st = r.json()
    states = st.get("results") if isinstance(st, dict) else st
    done_state = next((x["id"] for x in states if x["group"] == "completed"), None)

    created = skipped = 0
    for row in rows:
        name = f"{row['id']} — {row['title']}"
        if name in existing:
            skipped += 1
            continue
        payload = {
            "name": name,
            "description_html": (
                f"<p><b>State at import:</b> {row['state']}</p>"
                f"<p><b>Depends on:</b> {row['deps'] or '—'}</p>"
                f"<p><b>Notes:</b> {row['notes'] or '—'}</p>"
                f"<p>Source: PRD-vault-os.md / BACKLOG-plane-issues.md</p>"
            ),
        }
        if args.dry_run:
            print(f"would create: {name}")
            created += 1
            continue
        payload["labels"] = [
            label_id(f"difficulty:{row['difficulty']}"),
            label_id(f"module:{row['id'].split('.')[0]}"),
        ]
        if is_done(row["state"]) and done_state:
            payload["state"] = done_state
        r = s.post(f"{api}/issues/", json=payload, timeout=15)
        r.raise_for_status()
        created += 1
        print(f"created: {name}")

    print(f"done — created {created}, skipped {skipped} existing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
