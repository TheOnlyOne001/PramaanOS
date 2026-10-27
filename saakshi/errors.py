"""Last-resort error handling: an unhandled exception becomes a JSON 500 with a request id.

The full traceback goes to the server log under that id; the client only ever sees
`{"error": "internal_error", "request_id": "..."}`, so internals (SQL, paths, keys) never leak.
A caller-supplied `X-Request-ID` is reused when it is a short, safe token, so a support ticket
and the log line can be matched.
"""
from __future__ import annotations

import logging
import re
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"
_SAFE_ID = re.compile(r"[A-Za-z0-9._-]{8,64}")


def request_id(request: Request) -> str:
    """The caller's X-Request-ID when it is a safe token (no log injection), else a fresh random one."""
    supplied = request.headers.get(REQUEST_ID_HEADER, "")
    return supplied if _SAFE_ID.fullmatch(supplied) else uuid.uuid4().hex


async def unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
    """Log the exception with a request id and answer 500 with JSON instead of a stack trace."""
    rid = request_id(request)
    log.error("unhandled %s on %s %s (request_id=%s)", type(exc).__name__, request.method, request.url.path, rid,
              exc_info=exc)
    # Starlette serves this from its outermost middleware, outside the app's security-headers middleware,
    # so the headers that matter for an error body are set here.
    return JSONResponse({"error": "internal_error", "request_id": rid}, status_code=500,
                        headers={REQUEST_ID_HEADER: rid, "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


def install(app: FastAPI) -> None:
    """Register the last-resort handler on `app` (HTTPException and validation errors keep their own handlers)."""
    app.add_exception_handler(Exception, unhandled_exception)
