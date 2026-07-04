"""M2.3 — vault file-watcher: incremental re-index + node_update events.

watchdog observers run on their own thread; events are bridged onto the app's
asyncio loop and fanned out over the WS bus. Editing a note must update the
RAG index and emit a node_update within ~2s (AC).
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .bus import bus
from .config import settings
from .events import NodeUpdateEvent
from .rag import rag

SKIP_PARTS = {".obsidian", ".trash", ".git"}
DEBOUNCE_S = 0.5


class _Handler(FileSystemEventHandler):
    def __init__(self, loop: asyncio.AbstractEventLoop, vault: Path) -> None:
        self.loop = loop
        self.vault = vault
        self._last: dict[str, float] = {}

    def _relevant(self, event: FileSystemEvent) -> Path | None:
        if event.is_directory:
            return None
        p = Path(str(event.src_path))
        if p.suffix != ".md":
            return None
        try:
            rel = p.relative_to(self.vault)
        except ValueError:
            return None
        if any(part in SKIP_PARTS for part in rel.parts):
            return None
        # editors fire bursts of events per save — debounce per path
        now = time.monotonic()
        key = f"{event.event_type}:{rel}"
        if now - self._last.get(key, 0) < DEBOUNCE_S:
            return None
        self._last[key] = now
        return rel

    def _dispatch(self, action: str, rel: Path) -> None:
        asyncio.run_coroutine_threadsafe(
            handle_change(action, self.vault, rel), self.loop
        )

    def on_created(self, event: FileSystemEvent) -> None:
        if rel := self._relevant(event):
            self._dispatch("created", rel)

    def on_modified(self, event: FileSystemEvent) -> None:
        if rel := self._relevant(event):
            self._dispatch("updated", rel)

    def on_deleted(self, event: FileSystemEvent) -> None:
        if rel := self._relevant(event):
            self._dispatch("deleted", rel)

    def on_moved(self, event: FileSystemEvent) -> None:
        if rel := self._relevant(event):
            self._dispatch("deleted", rel)
        dest = Path(str(getattr(event, "dest_path", "")))
        if dest.suffix == ".md":
            try:
                self._dispatch("created", dest.relative_to(self.vault))
            except ValueError:
                pass


async def handle_change(action: str, vault: Path, rel: Path) -> None:
    rel_str = rel.as_posix()
    try:
        if action == "deleted":
            await asyncio.to_thread(rag().remove_file, rel_str)
        else:
            await asyncio.to_thread(rag().index_file, vault / rel)
    except Exception as e:  # a broken note must not kill the watcher
        print(f"[watcher] reindex failed for {rel_str}: {e}")
    await bus.emit(
        NodeUpdateEvent(
            ts=time.time(),
            source="indexer",
            action=action,  # type: ignore[arg-type]
            nodeId=rel_str,
            title=rel.stem,
        )
    )


class VaultWatcher:
    def __init__(self) -> None:
        self._observer: Observer | None = None

    def start(self, loop: asyncio.AbstractEventLoop) -> None:
        vault = Path(settings.vault_path)
        self._observer = Observer()
        self._observer.schedule(_Handler(loop, vault), str(vault), recursive=True)
        self._observer.daemon = True
        self._observer.start()
        print(f"[watcher] watching {vault}")

    def stop(self) -> None:
        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=3)


watcher = VaultWatcher()
