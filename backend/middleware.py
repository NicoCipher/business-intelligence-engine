"""
middleware.py — Request body size limits and security headers.

Kept separate from main.py to keep that file's responsibility (wiring
routers together) distinct from this one (cross-cutting request/response
concerns).
"""

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)

# Generous relative to this API's actual payloads -- a status-update body
# is a handful of bytes; nothing in this API legitimately needs more.
MAX_BODY_BYTES = 1_000_000  # 1 MB


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Rejects requests whose Content-Length exceeds MAX_BODY_BYTES with
    413, before the body is ever read into memory."""

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                size = int(content_length)
            except ValueError:
                size = 0
            if size > MAX_BODY_BYTES:
                return JSONResponse(
                    status_code=413,
                    content={"detail": f"Request body exceeds {MAX_BODY_BYTES} byte limit"},
                )
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    Adds standard defensive headers to every response. This is a
    JSON-only API -- all Signal-derived text (titles, content) must be
    rendered as text, never raw HTML, by any consuming frontend; these
    headers are defense-in-depth for that boundary, not a substitute for
    the frontend doing the right thing.
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        return response
