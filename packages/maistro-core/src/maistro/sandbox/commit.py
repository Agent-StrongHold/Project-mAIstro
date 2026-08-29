"""The one door a sandbox's output comes back through (#79).

A fence that travels but is never checked is decoration. Acceptance asks that
"mutable writes / branch promotion / artifact commits validate fence
freshness", and the way to make that true of *every* such path is to have one
path — a guard the publishing code cannot accomplish its work without going
through.

`fenced_commit` is that door. It re-reads the Attempt, refuses a superseded
fence, and only then runs the publish. The ordering is the substance: checking
afterwards would mean the side effect already happened, which is the thing
being prevented rather than a report of it.

What this cannot do is make the check atomic with the publish. Between the
assertion and the write, a recovery could still reclaim the lease. That race is
real and is *narrowed* here rather than closed, and it is why the canonical
store keeps its own fence on `transition_attempt`: a stale worker that slips
through this door still cannot record its result against the Attempt. This
guard exists to stop the external side effect — the branch push, the artifact
upload — that the store's fence cannot reach.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, TypeVar

from maistro.sandbox.fence import SandboxFence, assert_fence_is_current

if TYPE_CHECKING:  # pragma: no cover - typing only
    from maistro.runs.store import RunStore

logger = logging.getLogger("maistro.sandbox.commit")

T = TypeVar("T")


async def fenced_commit(
    fence: SandboxFence,
    publish: Callable[[], Awaitable[T]],
    *,
    run_store: RunStore,
    description: str,
) -> T:
    """Run `publish` only if this fence is still the current execution.

    `description` is required and is not decoration either: a refusal that
    cannot say *what* was refused leaves an operator knowing a stale worker
    was stopped and not knowing whether anything was left half-done.
    """
    await assert_fence_is_current(fence, run_store=run_store)
    logger.info(
        "sandbox_commit_admitted attempt=%s epoch=%d what=%s",
        fence.attempt_id,
        fence.lease_epoch,
        description,
    )
    return await publish()


__all__ = ["fenced_commit"]
