"""HTTP request/response logging for debugging (POC / HIVE_LOG_LEVEL=debug)."""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from routes import auth as auth_routes
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("hive.request")

_SKIP_PREFIXES = ("/favicon.ico", "/docs", "/openapi.json", "/redoc")
_OAUTH_CALLBACK_RE = re.compile(r"^/v1/auth/oauth/[^/]+/callback$")


def _safe_query(request: Request) -> dict[str, str] | None:
    if _OAUTH_CALLBACK_RE.fullmatch(request.url.path):
        return None
    return dict(request.query_params) or None


class RequestLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if any(path.startswith(p) for p in _SKIP_PREFIXES):
            return await call_next(request)

        if not path.startswith("/v1") and path not in ("/health", "/health/ready"):
            return await call_next(request)

        started = time.perf_counter()
        logger.debug(
            "→ %s %s query=%s session_cookie=%s",
            request.method,
            path,
            _safe_query(request),
            "present" if request.cookies.get("hive_session") else "-",
        )

        response: Response | None = None
        exc: BaseException | None = None
        try:
            response = await call_next(request)
            return response
        except BaseException as e:
            exc = e
            raise
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            status = response.status_code if response is not None else 500
            user = _safe_user(request)
            detail: dict[str, Any] = {
                "ms": round(elapsed_ms, 1),
                "status": status,
            }
            if user:
                detail["user"] = user.get("username")
            if exc is not None:
                detail["error"] = type(exc).__name__
            log_fn = logger.warning if status >= 400 else logger.info
            if logger.isEnabledFor(logging.DEBUG):
                log_fn = logger.debug
            log_fn(
                "← %s %s %s %s",
                request.method,
                path,
                status,
                detail,
            )


def _safe_user(request: Request) -> dict[str, Any] | None:
    try:
        sid = request.cookies.get("hive_session")
        if not sid:
            return None
        return auth_routes.get_current_user(sid)
    except Exception:
        return None
