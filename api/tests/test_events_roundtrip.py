"""M0.3 AC: shared fixtures round-trip through the Pydantic mirror losslessly."""

import json
from pathlib import Path

from pydantic import TypeAdapter

from vault_api.events import VaultEvent

FIXTURES = Path(__file__).resolve().parents[2] / "shared/fixtures/events.json"


def test_fixtures_roundtrip():
    raw = json.loads(FIXTURES.read_text())
    adapter = TypeAdapter(list[VaultEvent])
    events = adapter.validate_python(raw)
    assert len(events) == 6
    assert {e.type for e in events} == {
        "task_start",
        "file_diff",
        "log",
        "task_done",
        "node_update",
        "system_vital",
    }
    # round-trip: serialize back and compare to source
    back = json.loads(adapter.dump_json(events, exclude_none=True))
    assert back == raw
