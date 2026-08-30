"""Request correlation ID middleware.

Generates a unique request_id per HTTP request and binds it onto the canonical
execution context, so every log line, span and event under the request carries
it alongside whatever Run/NodeRun/Attempt ids the work goes on to acquire.
"""

from __future__ import annotations

import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from maistro.observability.correlation import bind_execution_context

logger = structlog.get_logger()


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a unique request_id to every request, propagate through logs."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]

        # Store on request state for exception handlers
        request.state.request_id = request_id

        # One vocabulary. This used to bind `request_id` straight into
        # structlog's contextvars, which correlated logs and nothing else: no
        # span, no event, and no path for the Run ids the request goes on to
        # create to join it. Binding through the execution context reaches all
        # three, and `execution_context_processor` still puts `request_id` on
        # every log line (#707).
        #
        # `clear_contextvars()` went with it. Starlette runs each request in
        # its own task, whose context is a copy, so there was nothing left
        # behind by a previous request to clear -- and clearing wiped bindings
        # an outer middleware had deliberately made.
        with bind_execution_context(request_id=request_id):
            response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
