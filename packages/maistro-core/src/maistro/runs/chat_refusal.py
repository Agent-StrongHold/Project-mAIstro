"""Refusing a chat turn that cannot get its canonical Run (#1108).

Owner decision (2026-09-23, amending ADR-082326-c126): every answered chat
turn has a canonical Run, NodeRun and Attempt. A turn that cannot be admitted,
or whose spine fails before the dispatch, is refused -- retryably -- and never
reaches the model outside the governed path. Answering it with `run_id: null`
was the rule this replaces.

A separate error from `ChatDispatchUnrecorded` on purpose: that one means the
model *did* answer and the record is short, so the answer goes back and the
Run stays open for recovery. This one means nothing was dispatched, so the
caller can safely try the whole turn again.
"""

from __future__ import annotations

from maistro.types.errors import AgentError

#: Seconds a refused caller is told to wait before retrying. Admission fails
#: on a store or project outage, which is transient but not instantaneous.
CHAT_TURN_RETRY_AFTER_S = 5


class ChatTurnRefused(AgentError):
    """The turn was not dispatched because it could not be governed by a Run.

    Retryable: nothing reached the model, so the same request can be sent
    again. HTTP doors map it to 503 with `Retry-After: retry_after_s`.
    """

    code = "CHAT_TURN_REFUSED"

    def __init__(self, detail: str, *, retry_after_s: int = CHAT_TURN_RETRY_AFTER_S) -> None:
        self.retry_after_s = retry_after_s
        super().__init__(detail)


__all__ = ["CHAT_TURN_RETRY_AFTER_S", "ChatTurnRefused"]
