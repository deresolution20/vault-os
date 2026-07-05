"""M5.2/M5.3 — model router: local-first lanes by difficulty, paid fallback.

Lanes (PRD §11.5): R9700 = senior (hard/long-context), 7900 XTX = junior
(trivial/easy parallel). Until the second card lands, all difficulties route
to whichever local lane is healthy. On local error/timeout/no-lane the
request escalates to the paid API (Anthropic) and the token ledger records
the spend so savings are measurable (M5.3 AC).

NEVER add a lane that spans two GPUs (PRD §3.1).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import httpx

from .config import settings

Difficulty = str  # trivial | easy | medium | hard

HEALTH_TTL_S = 10.0
LOCAL_TIMEOUT_S = 120.0


@dataclass
class Lane:
    id: str
    base_url: str  # OpenAI-compatible /v1
    tier: str  # "senior" | "junior"
    healthy: bool = False
    checked_at: float = 0.0


@dataclass
class TokenLedger:
    local_tokens: int = 0
    paid_tokens: int = 0
    local_requests: int = 0
    paid_requests: int = 0
    fallback_reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "localTokens": self.local_tokens,
            "paidTokens": self.paid_tokens,
            "localRequests": self.local_requests,
            "paidRequests": self.paid_requests,
            "lastFallbackReasons": self.fallback_reasons[-5:],
        }


class ModelRouter:
    def __init__(self) -> None:
        self.lanes = [
            Lane("r9700", settings.worker_r9700_url, tier="senior"),
            Lane("4060ti", settings.worker_4060ti_url, tier="junior"),
            Lane("7900xtx", settings.worker_7900xtx_url, tier="junior"),
        ]
        self.ledger = TokenLedger()

    async def _check(self, lane: Lane) -> bool:
        if time.monotonic() - lane.checked_at < HEALTH_TTL_S:
            return lane.healthy
        try:
            async with httpx.AsyncClient(timeout=3.0) as c:
                r = await c.get(f"{lane.base_url}/models")
                lane.healthy = r.status_code == 200
        except httpx.HTTPError:
            lane.healthy = False
        lane.checked_at = time.monotonic()
        return lane.healthy

    async def pick_lane(self, difficulty: Difficulty) -> Lane | None:
        """hard/medium prefer the senior card; trivial/easy the junior one.
        Falls through to any healthy lane before giving up."""
        preferred = "senior" if difficulty in ("hard", "medium") else "junior"
        ordered = sorted(self.lanes, key=lambda l: l.tier != preferred)
        for lane in ordered:
            if await self._check(lane):
                return lane
        return None

    async def complete(
        self,
        messages: list[dict],
        difficulty: Difficulty = "easy",
        max_tokens: int = 1024,
        lane_id: str | None = None,
    ) -> dict:
        """Local-first chat completion; escalates to paid API on failure.
        lane_id pins a specific card — if that lane is down, this errors
        loudly instead of silently detouring. Returns {content, lane, usage}."""
        if lane_id is not None:
            lane = next((l for l in self.lanes if l.id == lane_id), None)
            if lane is None:
                raise ValueError(f"unknown lane: {lane_id}")
            if not await self._check(lane):
                raise RuntimeError(
                    f"lane '{lane_id}' is down — start its worker or drop the pin"
                )
        else:
            lane = await self.pick_lane(difficulty)
        if lane is not None:
            try:
                async with httpx.AsyncClient(timeout=LOCAL_TIMEOUT_S) as c:
                    r = await c.post(
                        f"{lane.base_url}/chat/completions",
                        json={"messages": messages, "max_tokens": max_tokens},
                    )
                    r.raise_for_status()
                    data = r.json()
                usage = data.get("usage", {})
                self.ledger.local_requests += 1
                self.ledger.local_tokens += usage.get("total_tokens", 0)
                return {
                    "content": data["choices"][0]["message"]["content"],
                    "lane": lane.id,
                    "usage": usage,
                }
            except (httpx.HTTPError, KeyError) as e:
                lane.healthy = False
                self.ledger.fallback_reasons.append(f"{lane.id}: {e}")
        else:
            self.ledger.fallback_reasons.append("no healthy local lane")
        return await self._paid_fallback(messages, max_tokens)

    async def _paid_fallback(self, messages: list[dict], max_tokens: int) -> dict:
        """M5.3 — Anthropic API escalation. ⚠ burns paid credits."""
        if not settings.anthropic_api_key:
            raise RuntimeError(
                "no local lane available and ANTHROPIC_API_KEY unset — "
                "cannot escalate"
            )
        async with httpx.AsyncClient(timeout=120.0) as c:
            r = await c.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": settings.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": max_tokens,
                    "messages": messages,
                },
            )
            r.raise_for_status()
            data = r.json()
        usage = data.get("usage", {})
        total = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
        self.ledger.paid_requests += 1
        self.ledger.paid_tokens += total
        return {
            "content": data["content"][0]["text"],
            "lane": "paid-api",
            "usage": usage,
        }


model_router = ModelRouter()
