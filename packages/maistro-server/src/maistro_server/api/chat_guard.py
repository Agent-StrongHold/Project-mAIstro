"""The trust boundary and the execution identity for `/v1/chat/completions` (#150).

This endpoint calls `maistro.agents.conductor.run_task` directly rather than
going through `maistro.conduit`, so it inherits none of the pipeline every other
chat entry point does. #142 tracks the routing convergence, which needs a
`Container` and a populated agent map. Two of the things it skips do not need
either, and one of them is a security control:

**The Gate.** `CLAUDE.md` decision 6 is "All input is untrusted. Warden scans at
every trust boundary." This is an externally reachable boundary and it was not
scanned. `Gate.process_input` is the reusable primitive for exactly this — it
self-wires a `Warden` and takes no required arguments — so scanning here is
using the seam as intended, not bolting a second one on.

**The Run.** `wire_execution_spine` has returned a `chat_admitter` since #131 and
`maistro_server.main` discarded it. Admitting here wires something that already
exists.

Both are held in module state, set from the app lifespan, for the same reason
`api/runs.py` holds its store that way: this app has no DI container to read
them from, and the alternative — building a Gate per request — would mean every
request paying for a fresh Warden and no strike tracker ever accumulating.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:  # pragma: no cover - typing only
    from maistro.runs.chat import ChatRunAdmitter
    from maistro.runs.model import Run
    from maistro.security._types import GateResult
    from maistro.security.gate import Gate

logger = structlog.get_logger()

_gate: Gate | None = None
_chat_admitter: ChatRunAdmitter | None = None

#: What a blocked turn's Run records. The turn was refused at the boundary, so
#: it is cancelled rather than failed: nothing ran, and marking it FAILED would
#: make a policy refusal indistinguishable from work that broke. Same mapping
#: `maistro.conduit` uses for `OUTCOME_REFUSED`.
BLOCKED_RUN_ERROR_PREFIX = "Request blocked: "

#: The agent the admitted Graph names, because it is the one that runs.
#:
#: This endpoint calls `maistro.agents.conductor.run_task` directly, so the
#: executor is the conductor and nothing else. Left unset, `resolve_direct_work`
#: would fall through the intent table to its default — `artificer`, or `intake`
#: in PM mode — and the snapshot would name an agent this path never invokes.
#: That is the failure `maistro.runs.admission`'s docstring warns about: a Run
#: that is canonical in shape only, whose Graph replays as different work than
#: the turn it claims to record. Naming the conductor may not resolve in a
#: roster that has no entry for it, and that is the better failure of the two —
#: it is loud, where a wrong agent that happens to resolve is silent. #142's
#: routing convergence is what eventually makes this a genuine delegation.
CHAT_EXECUTOR_AGENT = "conductor"


def configure_chat_guard(gate: Gate | None, admitter: ChatRunAdmitter | None) -> None:
    """Install (or clear) the Gate and Run admitter this endpoint uses."""
    global _gate, _chat_admitter
    _gate = gate
    _chat_admitter = admitter


async def scan_prompt(prompt: str) -> GateResult | None:
    """Scan one prompt at the trust boundary, or None when no Gate is wired.

    None is not "allowed" — it is "not scanned", and the caller must decide what
    that means. It is returned rather than raised because a Gate is only absent
    in a process that built the app without a lifespan, which is every unit test
    that exercises the response shape.
    """
    if _gate is None:
        return None
    return await _gate.process_input(prompt, task_type="chat")


async def admit_turn(
    prompt: str,
    *,
    request_id: str = "",
    user_id: str = "",
    on_created: Callable[[Run], None] | None = None,
) -> Run | None:
    """Admit this turn as a canonical Run, or None when no spine is wired.

    ``user_id`` is the authenticated principal, and it becomes the Run's
    `actor_principal_id`. Omitting it made every Run this endpoint created
    anonymous, which ADR-082226-c126 cannot honour — a turn that cannot be
    attributed is a turn the audit cannot answer questions about.

    ``on_created`` is forwarded to the admitter so a caller that may be
    cancelled during admission still gets a reference to the Run; see
    `ChatRunAdmitter.admit_chat_turn`.
    """
    if _chat_admitter is None:
        return None
    return await _chat_admitter.admit_chat_turn(
        prompt=prompt,
        agent_name=CHAT_EXECUTOR_AGENT,
        request_id=request_id,
        user_id=user_id or None,
        on_created=on_created,
    )


async def close_turn(run: Run | None, *, error: str | None = None) -> None:
    """Close a turn's Run: COMPLETED, or CANCELLED when it was refused.

    Never raises. The caller has either produced an answer or is already
    unwinding a failure, and losing either to a bookkeeping error would be the
    worse trade — the same rule `Conduit._close_run` follows.
    """
    if run is None or _chat_admitter is None:
        return
    from maistro.runs.model import RunStatus

    status = RunStatus.COMPLETED if error is None else RunStatus.CANCELLED
    try:
        closed = await _chat_admitter.record_outcome(run.run_id, status, error=error)
    except Exception:
        await logger.aexception("chat_run_close_failed", run_id=run.run_id)
        return
    if not closed:
        await logger.aerror("chat_run_refused_close", run_id=run.run_id, target=status.value)


async def fail_turn(run: Run | None, *, error: str) -> None:
    """Close a turn's Run as FAILED — the agent ran and did not produce an answer."""
    if run is None or _chat_admitter is None:
        return
    from maistro.runs.model import RunStatus

    try:
        await _chat_admitter.record_outcome(run.run_id, RunStatus.FAILED, error=error)
    except Exception:
        await logger.aexception("chat_run_close_failed", run_id=run.run_id)


async def abandon_turn(run: Run | None, *, error: str) -> None:
    """Close a turn's Run at whatever state it actually reached.

    `fail_turn` assumes the Run is RUNNING, which is true once admission
    finished. A turn abandoned *during* admission is not: `CREATED -> FAILED`
    and `QUEUED -> FAILED` are not legal edges, so failing it would be refused
    and the record would stay open — the exact thing the caller is unwinding to
    prevent. `CANCELLED` is legal from both, and is also the truer word: nothing
    ran, so nothing failed.
    """
    if run is None or _chat_admitter is None:
        return
    from maistro.runs.model import RunStatus

    try:
        current = await _chat_admitter.record_outcome(
            run.run_id,
            RunStatus.FAILED if run.status is RunStatus.RUNNING else RunStatus.CANCELLED,
            error=error,
        )
    except Exception:
        await logger.aexception("chat_run_close_failed", run_id=run.run_id)
        return
    if not current:
        await logger.aerror("chat_run_refused_close", run_id=run.run_id, target="abandoned")


__all__ = [
    "BLOCKED_RUN_ERROR_PREFIX",
    "CHAT_EXECUTOR_AGENT",
    "abandon_turn",
    "admit_turn",
    "close_turn",
    "configure_chat_guard",
    "fail_turn",
    "scan_prompt",
]
