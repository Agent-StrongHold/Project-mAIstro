"""Request correlation ID middleware.

Adopts a client ``X-Request-ID`` only when exactly one header satisfies the
public request-ID contract. Missing, invalid, or duplicate values receive a
fresh server ID, which is then bound onto the canonical execution context so
every log line, span, and event under the request carries the effective ID.
The external telemetry boundary does not export ambient IDs because this
context does not prove whether a value was server- or client-generated.
"""

from __future__ import annotations

import re
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from maistro.observability.correlation import bind_execution_context

logger = structlog.get_logger()

REQUEST_ID_MAX_LENGTH = 128
"""Maximum accepted length of a client-supplied request ID."""

_REQUEST_ID_PATTERN = re.compile(rf"[A-Za-z0-9._-]{{1,{REQUEST_ID_MAX_LENGTH}}}")
_REQUEST_ID_ALPHANUMERIC_PATTERN = re.compile(r"[A-Za-z0-9]")


def _effective_request_id(candidates: list[str]) -> str:
    """Adopt one valid client ID or return a fresh server-generated ID.

    Accepted client IDs contain only ASCII letters, digits, dots, underscores,
    and hyphens, contain at least one letter or digit, and are bounded by
    ``REQUEST_ID_MAX_LENGTH``. Missing or duplicate fields are ambiguous and
    therefore generate a server ID.
    """
    if len(candidates) == 1:
        candidate = candidates[0]
        valid_characters = _REQUEST_ID_PATTERN.fullmatch(candidate)
        has_alphanumeric = _REQUEST_ID_ALPHANUMERIC_PATTERN.search(candidate)
        if valid_characters and has_alphanumeric:
            return candidate
    return uuid.uuid4().hex[:12]


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a safe request ID and propagate it through response metadata.

    Client IDs are preserved only when exactly one header contains 1-128 ASCII
    letters, digits, dots, underscores, or hyphens, including at least one
    letter or digit. Missing, duplicate, or invalid values are replaced with a
    server-generated ID before request state or execution context is bound.
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # SECURITY-REVIEW: This client-controlled header must be validated before
        # it can reach request state, logs, spans, events, or the response.
        request_id = _effective_request_id(request.headers.getlist("X-Request-ID"))

        # Store on request state for exception handlers
        request.state.request_id = request_id

        # One vocabulary. This used to bind `request_id` straight into
        # structlog's contextvars, which correlated logs and nothing else: no
        # span, no event, and no path for the Run ids the request goes on to
        # create to join it. Binding through the execution context reaches
        # local logs and events, and `execution_context_processor` still puts
        # `request_id` on every log line (#707). External spans intentionally
        # require stronger provenance than this ambient string context has.
        #
        # `clear_contextvars()` went with it. Starlette runs each request in
        # its own task, whose context is a copy, so there was nothing left
        # behind by a previous request to clear -- and clearing wiped bindings
        # an outer middleware had deliberately made.
        with bind_execution_context(request_id=request_id):
            response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
