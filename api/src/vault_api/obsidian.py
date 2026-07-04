"""M4.2 — Obsidian write layer via obsidian-local-rest-api (PRD §11.2).

The plugin serves HTTP on 127.0.0.1:27123 (HTTPS 27124) with bearer auth.
PUT /vault/{path} creates/replaces, POST appends, PATCH edits relative to a
heading. cyanheads/obsidian-mcp-server wraps this same surface for Hermes's
MCP-native tools; this client is the API layer's direct path.
"""

from __future__ import annotations

import httpx

from .config import settings


class ObsidianUnavailable(Exception):
    """Obsidian isn't running or the Local REST API plugin isn't enabled."""


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=settings.obsidian_rest_url,
        headers={"Authorization": f"Bearer {settings.obsidian_rest_api_key}"},
        timeout=5.0,
    )


async def write_note(path: str, content: str) -> None:
    """Create or replace a note (PUT /vault/{path})."""
    async with _client() as c:
        try:
            r = await c.put(
                f"/vault/{path}", content=content.encode(),
                headers={"Content-Type": "text/markdown"},
            )
        except httpx.ConnectError as e:
            raise ObsidianUnavailable(str(e)) from e
        r.raise_for_status()


async def append_note(path: str, content: str) -> None:
    """Append to a note, creating it if missing (POST /vault/{path})."""
    async with _client() as c:
        try:
            r = await c.post(
                f"/vault/{path}", content=content.encode(),
                headers={"Content-Type": "text/markdown"},
            )
        except httpx.ConnectError as e:
            raise ObsidianUnavailable(str(e)) from e
        r.raise_for_status()


async def patch_note(path: str, content: str, heading: str) -> None:
    """Insert content relative to a heading (PATCH /vault/{path})."""
    async with _client() as c:
        try:
            r = await c.patch(
                f"/vault/{path}", content=content.encode(),
                headers={
                    "Content-Type": "text/markdown",
                    "Operation": "append",
                    "Target-Type": "heading",
                    "Target": heading,
                },
            )
        except httpx.ConnectError as e:
            raise ObsidianUnavailable(str(e)) from e
        r.raise_for_status()


async def is_up() -> bool:
    async with _client() as c:
        try:
            r = await c.get("/")
            return r.status_code < 500
        except httpx.HTTPError:
            return False
