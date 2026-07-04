"""M2.3 AC: editing a note updates the index and pushes node_update < ~2s.

Uses a temp vault (not the real one) via env override, a live uvicorn-less
TestClient WS, and a real watchdog observer.
"""

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "Seed.md").write_text("# Seed\nHello [[World]]\n")

    from vault_api import config

    monkeypatch.setattr(config.settings, "vault_path", vault)
    monkeypatch.setattr(config.settings, "rag_data_dir", tmp_path / "rag")
    monkeypatch.setattr(config.settings, "hermes_api_token", "")

    # fresh RagService bound to the temp vault
    from vault_api import rag as rag_mod

    rag_mod.rag.cache_clear()

    from vault_api.main import app

    with TestClient(app) as c:
        c.vault = vault
        yield c
    rag_mod.rag.cache_clear()


def test_node_update_within_2s(client):
    with client.websocket_connect("/ws/events") as ws:
        assert ws.receive_json()["type"] == "log"  # connect banner

        start = time.monotonic()
        (client.vault / "NewNote.md").write_text("# New Note\nfresh thought\n")

        evt = ws.receive_json()
        elapsed = time.monotonic() - start
        assert evt["type"] == "node_update"
        assert evt["nodeId"] == "NewNote.md"
        assert evt["action"] in ("created", "updated")
        assert elapsed < 2.0, f"took {elapsed:.2f}s"

    # index actually grew (embeds via local ollama)
    from vault_api.rag import rag

    assert any(
        h["metadata"]["file_path"] == "NewNote.md"
        for h in rag().query("fresh thought", 5)
    )
