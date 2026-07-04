"""M4.4 — local bearer-token auth. Localhost-only binding is enforced at the
uvicorn layer (--host 127.0.0.1); this guards every route + the WS upgrade.

If HERMES_API_TOKEN is unset (fresh clone), auth is disabled with a startup
warning — the server still only listens on loopback.
"""

from fastapi import Depends, HTTPException, Request, WebSocket, status

from .config import settings


def _ok(token_header: str | None) -> bool:
    expected = settings.hermes_api_token
    if not expected:
        return True
    return token_header == f"Bearer {expected}"


async def require_token(request: Request) -> None:
    if not _ok(request.headers.get("authorization")):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or missing token")


async def require_ws_token(ws: WebSocket) -> bool:
    """WS clients pass the token as ?token=… or an Authorization header."""
    expected = settings.hermes_api_token
    if not expected:
        return True
    header = ws.headers.get("authorization")
    query = ws.query_params.get("token")
    return header == f"Bearer {expected}" or query == expected


auth_required = Depends(require_token)
