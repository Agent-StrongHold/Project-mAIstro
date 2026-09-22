from __future__ import annotations

import logging

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

logger = logging.getLogger("hive.privilege_middleware")

_ADMIN_PATHS: frozenset[str] = frozenset()
_ADMIN_PREFIXES = ("/v1/settings",)


class PrivilegeMiddleware(BaseHTTPMiddleware):
    """Placeholder middleware boundary for future path-level privilege checks.

    The class remains installed as an adapter seam even while the current policy
    table is empty, so future settings/admin restrictions can be added without
    changing FastAPI application wiring.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        return await call_next(request)
