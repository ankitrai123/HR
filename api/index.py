"""Vercel entrypoint: runs the FastAPI app in backend/api_server.py as a Python
serverless function.

vercel.json rewrites /api/* and /health here; the request keeps its original
path, so the app's /api/... routes match unchanged. The static web app in dist/
is served by Vercel itself.

If the app can't start (missing environment variables, unreachable database)
every request gets a 503 with a readable reason instead of Vercel's generic
crash page, and the next request tries again.
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable

BACKEND = Path(__file__).resolve().parent.parent / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

log = logging.getLogger("assessment.vercel")

ASGIApp = Callable[[dict, Callable[[], Awaitable[dict]], Callable[[dict], Awaitable[None]]], Awaitable[None]]


def _build() -> ASGIApp:
    from api_server import app as fastapi_app  # creates the app (and missing tables) on import

    return fastapi_app


_app: ASGIApp | None = None


def _startup_error(exc: Exception) -> str:
    message = str(exc)
    if message.startswith(("invalid configuration:", "RESPONSE_ENCRYPTION_KEY")):
        return f"The server isn't configured yet: {message.removeprefix('invalid configuration: ')}."
    return ("The server couldn't start: it could not connect to the database or initialise "
            f"({type(exc).__name__}). Check DATABASE_URL and the function logs in Vercel.")


async def _send_json(send: Callable[[dict], Awaitable[None]], status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"cache-control", b"no-store"),
                            (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


async def app(scope: dict, receive: Callable[[], Awaitable[dict]], send: Callable[[dict], Awaitable[None]]) -> None:
    global _app
    if _app is None:
        try:
            _app = _build()
        except Exception as exc:  # report it on every request until it starts
            log.exception("failed to start the API")
            if scope["type"] == "http":
                await _send_json(send, 503, {"detail": _startup_error(exc)})
            return
    await _app(scope, receive, send)
