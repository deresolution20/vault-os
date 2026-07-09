"""M2.3 AC: editing a note updates the index and pushes node_update < ~2s.

Uses a temp vault (not the real one) and exercises the watcher change handler
directly. RAG is faked here so the watcher test does not depend on a live
embedding server.
"""

import time
import asyncio
from types import SimpleNamespace
from pathlib import Path

import pytest


class FakeRag:
    def __init__(self) -> None:
        self.indexed: set[str] = set()

    def index_file(self, path: str | Path) -> int:
        self.indexed.add(Path(path).name)
        return 1

    def remove_file(self, rel_path: str) -> None:
        self.indexed.discard(Path(rel_path).name)

    def query(self, text: str, limit: int = 8) -> list[dict]:
        if "NewNote.md" not in self.indexed:
            return []
        return [{"metadata": {"file_path": "NewNote.md"}}]


@pytest.fixture
def watcher_context(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Seed.md").write_text("# Seed\nHello [[World]]\n")

    from vault_api import config

    monkeypatch.setattr(config.settings, "vault_path", vault)
    monkeypatch.setattr(config.settings, "rag_data_dir", tmp_path / "rag")
    monkeypatch.setattr(config.settings, "hermes_api_token", "")

    from vault_api import rag as rag_mod

    fake_rag = FakeRag()

    def get_fake_rag() -> FakeRag:
        return fake_rag

    monkeypatch.setattr(rag_mod, "rag", get_fake_rag)
    try:
        from vault_api import watcher as watcher_mod

        monkeypatch.setattr(watcher_mod, "rag", get_fake_rag)
    except ImportError:
        pass

    from vault_api import watcher as watcher_mod

    return SimpleNamespace(watcher=watcher_mod, vault=vault, fake_rag=fake_rag)


def test_node_update_within_2s(watcher_context, monkeypatch):
    events = []

    async def collect(event):
        events.append(event)

    async def run_sync(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr(watcher_context.watcher.bus, "emit", collect)
    monkeypatch.setattr(watcher_context.watcher.asyncio, "to_thread", run_sync)
    asyncio.run(_run_node_update(watcher_context))

    assert events
    evt = events[0]
    assert evt.type == "node_update"
    assert evt.nodeId == "NewNote.md"
    assert evt.action == "created"

    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        if any(
            h["metadata"]["file_path"] == "NewNote.md"
            for h in watcher_context.fake_rag.query("fresh thought", 5)
        ):
            break
        time.sleep(0.1)
    else:
        raise AssertionError("NewNote.md never appeared in the RAG index")


async def _run_node_update(watcher_context):
    note = watcher_context.vault / "NewNote.md"
    note.write_text("# New Note\nfresh thought\n")

    start = time.monotonic()
    await watcher_context.watcher.handle_change(
        "created", watcher_context.vault, Path("NewNote.md")
    )
    elapsed = time.monotonic() - start
    assert elapsed < 2.0, f"took {elapsed:.2f}s"
