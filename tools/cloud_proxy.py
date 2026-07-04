#!/usr/bin/env python3
"""vault-cloud-proxy — transparent relay in front of https://ollama.com.

Hermes's orchestrator points its base_url at http://127.0.0.1:11500/v1; every
request passes through unchanged (Authorization included, never stored or
logged) while the relay records model / tokens / latency so the VAULT gpu-deck
can show the CLOUD ORCHESTRATOR lane.

Standalone BY DESIGN: no vault_api imports — VAULT API restarts must never
break the orchestrator. Stats land in projects/vault-os/.tmp/ as plain files.

Run: uv run --with fastapi --with "uvicorn[standard]" --with httpx \
       python3 tools/cloud_proxy.py
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import Response, StreamingResponse

UPSTREAM = "https://ollama.com"
PORT = 11500
ROOT = Path(__file__).resolve().parents[1]
STATS = ROOT / ".tmp/cloud-proxy-stats.jsonl"
LIVE = ROOT / ".tmp/cloud-proxy-live.json"
ROTATE_LINES = 5000

# hop-by-hop headers must not be forwarded either direction
HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length",
}

app = FastAPI()
client = httpx.AsyncClient(base_url=UPSTREAM, timeout=httpx.Timeout(600.0))
_in_flight: dict[int, dict] = {}  # id(request) -> {"model", "startedTs"}
_lock = asyncio.Lock()


def _write_live() -> None:
    LIVE.parent.mkdir(parents=True, exist_ok=True)
    entries = list(_in_flight.values())
    LIVE.write_text(
        json.dumps(
            {
                # legacy key kept for older readers
                "inFlightModels": [e["model"] for e in entries],
                "inFlight": entries,
            }
        )
    )


def _append_stat(rec: dict) -> None:
    STATS.parent.mkdir(parents=True, exist_ok=True)
    with STATS.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    # size-bounded: rotate by keeping the newest half when the cap is hit
    try:
        lines = STATS.read_text().splitlines()
        if len(lines) > ROTATE_LINES:
            STATS.write_text("\n".join(lines[-ROTATE_LINES // 2 :]) + "\n")
    except OSError:
        pass


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


@app.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
)
async def relay(request: Request, path: str) -> Response:
    body = await request.body()
    model = None
    is_stream = False
    injected = False
    if body:
        try:
            payload = json.loads(body)
            model = payload.get("model")
            is_stream = bool(payload.get("stream"))
            # ask upstream to include usage in the final SSE chunk so token
            # counts are exact; stripped again if upstream rejects it
            if is_stream and "stream_options" not in payload:
                payload["stream_options"] = {"include_usage": True}
                body = json.dumps(payload).encode()
                injected = True
        except ValueError:
            pass

    headers = {
        k: v for k, v in request.headers.items() if k.lower() not in HOP
    }
    started = time.time()
    key = id(request)
    async with _lock:
        if model:
            _in_flight[key] = {"model": model, "startedTs": started}
            _write_live()

    async def finish(status: int, tokens_in, tokens_out, approx: bool) -> None:
        async with _lock:
            _in_flight.pop(key, None)
            _write_live()
        if not model:
            return  # non-inference call (model list, health, …) — don't log
        _append_stat(
            {
                "ts": started,
                "model": model,
                "path": f"/{path}",
                "status": status,
                "durationMs": int((time.time() - started) * 1000),
                "tokensIn": tokens_in,
                "tokensOut": tokens_out,
                "approx": approx,
                "stream": is_stream,
            }
        )

    req = client.build_request(
        request.method, f"/{path}", content=body, headers=headers,
        params=request.query_params,
    )

    try:
        upstream = await client.send(req, stream=True)
    except httpx.HTTPError as e:
        await finish(502, None, None, False)
        return Response(f"upstream error: {e}", status_code=502)

    # retry once without the injected stream_options if upstream balks
    if injected and upstream.status_code == 400:
        await upstream.aclose()
        original = json.loads(body)
        original.pop("stream_options", None)
        req = client.build_request(
            request.method, f"/{path}", content=json.dumps(original).encode(),
            headers=headers, params=request.query_params,
        )
        try:
            upstream = await client.send(req, stream=True)
        except httpx.HTTPError as e:
            await finish(502, None, None, False)
            return Response(f"upstream error: {e}", status_code=502)

    resp_headers = {
        k: v for k, v in upstream.headers.items() if k.lower() not in HOP
    }

    if not is_stream:
        raw = await upstream.aread()
        await upstream.aclose()
        tokens_in = tokens_out = None
        approx = False
        try:
            usage = json.loads(raw).get("usage") or {}
            tokens_in = usage.get("prompt_tokens")
            tokens_out = usage.get("completion_tokens")
        except ValueError:
            pass
        if model and tokens_out is None:
            tokens_out = _estimate_tokens(raw.decode(errors="replace"))
            approx = True
        await finish(upstream.status_code, tokens_in, tokens_out, approx)
        return Response(
            raw, status_code=upstream.status_code, headers=resp_headers
        )

    async def stream():
        tokens_in = tokens_out = None
        chars = 0
        try:
            async for chunk in upstream.aiter_bytes():
                chars += len(chunk)
                # scan SSE data lines for the usage chunk
                for line in chunk.split(b"\n"):
                    if line.startswith(b"data: {"):
                        try:
                            d = json.loads(line[6:])
                            u = d.get("usage")
                            if u:
                                tokens_in = u.get("prompt_tokens")
                                tokens_out = u.get("completion_tokens")
                        except ValueError:
                            pass
                yield chunk
        finally:
            await upstream.aclose()
            approx = tokens_out is None
            if approx:
                tokens_out = max(1, chars // 16)  # rough SSE-overhead guess
            await finish(upstream.status_code, tokens_in, tokens_out, approx)

    return StreamingResponse(
        stream(), status_code=upstream.status_code, headers=resp_headers
    )


if __name__ == "__main__":
    _write_live()
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
