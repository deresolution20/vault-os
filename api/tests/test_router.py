"""M5.2/M5.3 AC (mocked): lane pick by difficulty, health checks, fallback.

Real-GPU serving is verified by tools/test_worker.sh; real paid fallback is
NOT exercised here (burns credits — needs explicit approval, PRD §3.9).
"""

import httpx
import pytest

from vault_api.router import Lane, ModelRouter


class FakeRouter(ModelRouter):
    """Health + completion stubs controllable per lane."""

    def __init__(self, health: dict[str, bool]):
        super().__init__()
        self._health = health
        self.completed_on: list[str] = []
        self.paid_called = False

    async def _check(self, lane: Lane) -> bool:
        lane.healthy = self._health.get(lane.id, False)
        return lane.healthy

    async def _paid_fallback(self, messages, max_tokens):
        self.paid_called = True
        self.ledger.paid_requests += 1
        self.ledger.paid_tokens += 42
        return {"content": "paid", "lane": "paid-api", "usage": {}}


@pytest.mark.asyncio
async def test_hard_prefers_senior_lane():
    r = FakeRouter({"r9700": True, "7900xtx": True})
    assert [lane.id for lane in r.lanes] == ["r9700", "7900xtx"]
    assert (await r.pick_lane("hard")).id == "r9700"
    assert (await r.pick_lane("trivial")).id == "7900xtx"


@pytest.mark.asyncio
async def test_falls_through_to_other_healthy_lane():
    r = FakeRouter({"r9700": True, "7900xtx": False})
    assert (await r.pick_lane("trivial")).id == "r9700"


@pytest.mark.asyncio
async def test_no_lane_escalates_to_paid():
    r = FakeRouter({"r9700": False, "7900xtx": False})
    out = await r.complete([{"role": "user", "content": "hi"}])
    assert out["lane"] == "paid-api"
    assert r.paid_called
    assert r.ledger.paid_requests == 1
    assert "no healthy local lane" in r.ledger.fallback_reasons[-1]


@pytest.mark.asyncio
async def test_local_error_escalates_and_marks_unhealthy(monkeypatch):
    r = FakeRouter({"r9700": True, "7900xtx": False})

    class BoomClient:
        def __init__(self, *a, **k): ...
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a):
            return False
        async def post(self, *a, **k):
            raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx, "AsyncClient", BoomClient)
    out = await r.complete([{"role": "user", "content": "hi"}], "hard")
    assert out["lane"] == "paid-api"
    assert r.lanes[0].healthy is False
    assert "boom" in r.ledger.fallback_reasons[-1]
