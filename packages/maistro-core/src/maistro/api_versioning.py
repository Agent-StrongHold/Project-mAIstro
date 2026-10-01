"""API-wide HTTP version negotiation ([ADR-076](../../docs/adr/ADR-076-http-api-versioning.md)).

The HTTP API versions by **content negotiation**, not by path-splitting: the
URL identifies the resource (the stable ``/v1`` route mount), the negotiated
version identifies the representation. A request selects a version one of
three ways, checked in this precedence order (first selector wins; the ADR
only requires that every form resolves to the same version for the same
request, which precedence guarantees):

1. ``Accept: application/vnd.maistro.vN`` (preferred; ``+json`` suffix and
   media-type parameters are tolerated),
2. an ``api_version`` query parameter,
3. an ``api_version`` field in a JSON request body.

A request with no selector resolves to the default version, which every
response advertises in the ``Maistro-API-Version`` (what served it) and
``Maistro-API-Default`` (what silence buys) headers. A request naming an
unsupported version is a ``406``; a selector that is present but not an
integer is a ``400``. Negotiation errors answer before any route handler or
downstream middleware runs, so a bad selector never reaches business logic.

When a response's media type is plain ``application/json`` and the client
selected its version through the ``Accept`` media type, the response media
type is rewritten to ``application/vnd.maistro.vN+json`` — the ADR's example
contract. Clients that selected through the query/body field, and clients
that did not negotiate at all, keep ``application/json`` so strict parsers
are never surprised. Vendor media types negotiated by a sub-surface (e.g.
canvas's ``application/vnd.canvas+json;version=2``) are never rewritten:
they are that surface's own mechanism, not this one.

A deprecated version's responses carry ``Deprecation`` / ``Sunset`` /
``Link`` headers naming the migration path. No version is deprecated today;
the plumbing is exercised by tests so the first deprecation needs a table
row, not new code.

The middleware is plain ASGI so it sits outside any BaseHTTPMiddleware
event-loop hop. Non-HTTP scopes (WebSocket, lifespan) pass through
untouched. A JSON body is read eagerly only up to a small cache cap (small
bodies only — the point of the body form is field selection, not bulk
transfer) and replayed to the downstream app verbatim, so payload limits and
webhook signature checks see the same bytes they always did; a body beyond
the cap is simply never buffered and the body form does not resolve.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, cast

__all__ = [
    "API_VERSIONS",
    "DEFAULT_API_VERSION",
    "MAISTRO_API_DEFAULT_HEADER",
    "MAISTRO_API_VERSION_HEADER",
    "ApiVersion",
    "VersionNegotiationMiddleware",
    "negotiated_api_version",
]

MAISTRO_API_VERSION_HEADER = "Maistro-API-Version"
MAISTRO_API_DEFAULT_HEADER = "Maistro-API-Default"

_MEDIA_TYPE_PREFIX = "application/vnd.maistro.v"
_DEFAULT_CONTENT_TYPE = "application/json"
#: Body-form selectors are only read from bodies up to this many bytes; a
#: larger body is streamed through unbuffered (header/query forms still work).
BODY_CACHE_CAP_BYTES = 1_048_576


@dataclass(frozen=True)
class ApiVersion:
    """One supported API version and its deprecation signalling."""

    number: int
    deprecated: bool = False
    sunset: str | None = None
    migration_link: str | None = None


#: The supported versions. A breaking change adds a row here and increments
#: nothing else — routes stay on their stable mounts.
API_VERSIONS: dict[int, ApiVersion] = {
    1: ApiVersion(number=1),
}

#: The version a request with no selector gets.
DEFAULT_API_VERSION = 1


def _parse_accept_version(accept: str | None) -> int | None | str:
    """Extract the negotiated version from an ``Accept`` header.

    Returns ``None`` when no maistro media type is present, the integer
    version when one is, or a string describing the malformed selector (a
    ``vnd.maistro`` media type with no parseable version is a negotiation
    attempt, so it is an error rather than a silent ignore).
    """
    if not accept:
        return None
    for raw_part in accept.split(","):
        part = raw_part.strip()
        if not part.startswith(_MEDIA_TYPE_PREFIX):
            continue
        tail = part[len(_MEDIA_TYPE_PREFIX) :]
        digits = ""
        for char in tail:
            if char.isdigit():
                digits += char
            else:
                break
        if not digits:
            return part
        return int(digits)
    return None


def _selector_from_query(query_string: bytes) -> int | None | str:
    """Extract ``api_version`` from the raw query string, if present."""
    if not query_string:
        return None
    for pair in query_string.decode("latin-1").split("&"):
        key, _, value = pair.partition("=")
        if key != "api_version":
            continue
        value = value.strip()
        if value.isdigit():
            return int(value)
        return f"non-integer api_version query parameter {value!r}"
    return None


def _selector_from_body(body: bytes) -> int | None | str:
    """Extract ``api_version`` from a JSON body, if the field is present.

    An absent, non-JSON, or non-object body is simply not a selector — the
    route handlers answer for the body's own validity.
    """
    try:
        document = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(document, dict):
        return None
    if "api_version" not in document:
        return None
    value = document["api_version"]
    if isinstance(value, bool):
        return f"non-integer api_version body field {value!r}"
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return f"non-integer api_version body field {value!r}"


def negotiated_api_version(
    accept: str | None,
    query_string: bytes,
    body: bytes,
    versions: dict[int, ApiVersion],
    default: int,
) -> tuple[int | None, str | None, str | None]:
    """Resolve the negotiated version, or an error message.

    Returns ``(version, error, form)``. ``(version, None, form)`` is a
    resolution: ``version`` is the selected version or ``None`` when no
    selector was present at all (meaning "serve the default"), and ``form``
    names the winning selector — ``"accept"``, ``"query"``, ``"body"`` —
    so the caller can tell an Accept-negotiated request (whose response
    media type is rewritten to the versioned type) from one that selected
    through the query/body field (whose response stays plain JSON).
    ``(None, error, None)`` is a rejected selector.

    Selector precedence: ``Accept`` media type, then ``api_version`` query
    parameter, then ``api_version`` JSON body field.
    """
    for form, selector in (
        ("accept", _parse_accept_version(accept)),
        ("query", _selector_from_query(query_string)),
        ("body", _selector_from_body(body)),
    ):
        if selector is None:
            continue
        if isinstance(selector, str):
            return None, selector, None
        if selector not in versions:
            supported = ", ".join(str(number) for number in sorted(versions))
            return (
                None,
                f"Unsupported API version {selector}; supported: {supported}",
                None,
            )
        return selector, None, form
    return None, None, None


def _deprecation_headers(spec: ApiVersion) -> list[tuple[bytes, bytes]]:
    headers: list[tuple[bytes, bytes]] = [(b"deprecation", b"true")]
    if spec.sunset is not None:
        headers.append((b"sunset", spec.sunset.encode("latin-1")))
    if spec.migration_link is not None:
        headers.append((b"link", f'<{spec.migration_link}>; rel="deprecation"'.encode("latin-1")))
    return headers


def versioned_content_type(content_type: str, version: int) -> str | None:
    """Rewrite plain ``application/json`` to the versioned media type.

    Returns ``None`` when the response's media type is not plain JSON — a
    vendor media type belongs to its own sub-surface and is never rewritten.
    """
    if content_type.split(";", 1)[0].strip() != _DEFAULT_CONTENT_TYPE:
        return None
    rewritten = f"{_MEDIA_TYPE_PREFIX}{version}+json"
    if ";" in content_type:
        return f"{rewritten};{content_type.split(';', 1)[1]}"
    return rewritten


def _replaying_receive(
    receive: Any, buffered: bytes, drained: list[dict[str, Any]], overflow: bool
) -> Any:
    """Build a receive that replays the cached body, then proxies live reads.

    All state is per-request closure state — the middleware instance itself
    never holds request state, so concurrent requests cannot cross wires.
    """
    queue: list[dict[str, Any]]
    if overflow:
        # The drain stopped mid-stream: replay exactly what was seen, then
        # proxy the live stream for the rest.
        queue = list(drained)
    elif drained:
        # Fully drained: a re-chunked stream carrying the same bytes is
        # ASGI-equivalent and simpler to replay.
        queue = [{"type": "http.request", "body": buffered, "more_body": False}]
    else:
        # Nothing was drained (non-JSON body, or a declared body over the
        # cap): pure proxy, never an injected terminator.
        queue = []

    async def wrapped_receive() -> dict[str, Any]:
        if queue:
            message: dict[str, Any] = queue.pop(0)
            return message
        return cast("dict[str, Any]", await receive())

    return wrapped_receive


class VersionNegotiationMiddleware:
    """Pure-ASGI middleware implementing ADR-076 version negotiation.

    Constructed through ``app.add_middleware(VersionNegotiationMiddleware,
    versions=API_VERSIONS, default_version=DEFAULT_API_VERSION,
    skip_prefixes=...)``. Paths under any skip prefix (health, metrics,
    OpenAPI/docs, A2A — the ADR scopes A2A and MCP versioning out) pass
    through with no negotiation semantics at all.
    """

    def __init__(
        self,
        app: Any,
        versions: dict[int, ApiVersion] | None = None,
        default_version: int = DEFAULT_API_VERSION,
        skip_prefixes: tuple[str, ...] = (),
        body_cache_cap_bytes: int = BODY_CACHE_CAP_BYTES,
    ) -> None:
        self.app = app
        self.versions = versions if versions is not None else API_VERSIONS
        self.default_version = default_version
        self.skip_prefixes = skip_prefixes
        self.body_cache_cap_bytes = body_cache_cap_bytes

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        for prefix in self.skip_prefixes:
            if path == prefix or path.startswith(prefix.rstrip("/") + "/"):
                await self.app(scope, receive, send)
                return

        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        buffered, drained, overflow = await self._cache_body(receive, headers)

        version, error, form = negotiated_api_version(
            headers.get("accept"),
            scope.get("query_string", b""),
            buffered,
            self.versions,
            self.default_version,
        )
        if error is not None:
            await self._reject(send, error)
            return

        await self.app(
            scope,
            _replaying_receive(receive, buffered, drained, overflow),
            self._send_with_version_headers(send, version, form),
        )

    async def _cache_body(
        self, receive: Any, headers: dict[str, str]
    ) -> tuple[bytes, list[dict[str, Any]], bool]:
        """Read a JSON request body up to the cache cap.

        Returns ``(buffered, drained, overflow)``. Only ``application/json``
        bodies are buffered (only they can carry the body-form selector);
        anything else streams through untouched and nothing is drained. On
        overflow the *buffer* is abandoned but the drained messages are kept
        for replay, so the downstream app sees the same byte stream it always
        did (and the payload-size middleware still applies its own limits).
        """
        content_type = headers.get("content-type", "")
        if content_type.split(";", 1)[0].strip() != _DEFAULT_CONTENT_TYPE:
            return b"", [], False
        # A declared body larger than the cap never buffers; the payload-size
        # middleware answers for it if it is over that limit too.
        content_length = headers.get("content-length")
        if (
            content_length is not None
            and content_length.isdigit()
            and int(content_length) > self.body_cache_cap_bytes
        ):
            return b"", [], False

        chunks: list[bytes] = []
        drained: list[dict[str, Any]] = []
        total = 0
        overflow = False
        while True:
            message = await receive()
            drained.append(message)
            if message["type"] == "http.disconnect":
                return b"", drained, False
            if message["type"] != "http.request":
                continue
            chunk = message.get("body", b"")
            total += len(chunk)
            if total > self.body_cache_cap_bytes:
                overflow = True
                break
            if chunk:
                chunks.append(chunk)
            if not message.get("more_body"):
                break
        return b"".join(chunks), drained, overflow

    def _send_with_version_headers(self, send: Any, version: int | None, form: str | None) -> Any:
        async def wrapped_send(message: dict[str, Any]) -> None:
            if message["type"] != "http.response.start":
                await send(message)
                return
            served = version if version is not None else self.default_version
            spec = self.versions[served]
            raw_headers = list(message.get("headers", []))
            raw_headers.append((MAISTRO_API_VERSION_HEADER.encode(), str(served).encode()))
            raw_headers.append(
                (MAISTRO_API_DEFAULT_HEADER.encode(), str(self.default_version).encode())
            )
            if spec.deprecated:
                raw_headers.extend(_deprecation_headers(spec))
            if version is not None and form == "accept":
                # Only an Accept-negotiated request gets the versioned media
                # type back: the client declared it understands vendor types.
                # Query/body-selected responses stay plain JSON.
                response_content_type = next(
                    (
                        value.decode("latin-1")
                        for key, value in raw_headers
                        if key == b"content-type"
                    ),
                    "",
                )
                rewritten = versioned_content_type(response_content_type, version)
                if rewritten is not None:
                    raw_headers = [
                        (
                            key,
                            rewritten.encode("latin-1") if key == b"content-type" else value,
                        )
                        for key, value in raw_headers
                    ]
            await send({**message, "headers": raw_headers})

        return wrapped_send

    async def _reject(self, send: Any, error: str) -> None:
        status = 400 if error.startswith("non-integer") else 406
        payload = json.dumps({"detail": error}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(payload)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": payload})
