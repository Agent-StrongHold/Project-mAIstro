"""Bound operator evidence before version negotiation and never reflect selectors."""

from __future__ import annotations

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_RESOLUTION_BYTES = 65536
_PREFIX = "/v1/invocations"
_INVALID_REQUEST = b'{"detail":"Invalid API version selector or request"}'


async def _bounded_messages(receive: Receive) -> list[Message] | None:
    messages: list[Message] = []
    size = 0
    while True:
        message = await receive()
        size += len(message.get("body", b""))
        if size > MAX_RESOLUTION_BYTES:
            return None
        messages.append(message)
        if message["type"] == "http.disconnect" or not message.get("more_body", False):
            return messages


def _replay(messages: list[Message], receive: Receive) -> Receive:
    pending = iter(messages)

    async def replay() -> Message:
        try:
            return next(pending)
        except StopIteration:
            return await receive()

    return replay


def _safe_errors(send: Send) -> Send:
    redact = False
    sent = False

    async def safe_send(message: Message) -> None:
        nonlocal redact, sent
        if message["type"] == "http.response.start":
            redact = message["status"] in {400, 406}
            if redact:
                headers = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() != b"content-length"
                ]
                headers.append((b"content-length", str(len(_INVALID_REQUEST)).encode()))
                message = {**message, "headers": headers}
        if redact and message["type"] == "http.response.body":
            if not sent:
                await send(
                    {"type": "http.response.body", "body": _INVALID_REQUEST, "more_body": False}
                )
                sent = True
            return
        await send(message)

    return safe_send


class InvocationIngressMiddleware:
    """Protect this operator door while delegating version selection unchanged."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or not (path == _PREFIX or path.startswith(_PREFIX + "/")):
            await self.app(scope, receive, send)
            return
        messages = await _bounded_messages(receive)
        if messages is None:
            await JSONResponse(
                {"detail": "reconciliation request exceeds 64 KiB"}, status_code=413
            )(scope, receive, send)
            return
        await self.app(scope, _replay(messages, receive), _safe_errors(send))
