"""Carry Attempt fencing across the sandbox boundary (#79, depends on #45).

#45 put a fence on the canonical store: `transition_attempt(fencing_token=...)`
refuses a write whose token is not the Attempt's current one, so a worker whose
lease was reclaimed cannot overwrite the Attempt that replaced it. That fence
stops at the process edge. A sandboxed worker is a *different process* — often
a different namespace, and by #76 sometimes a different kernel — and everything
it publishes comes back across a boundary the store has never seen.

So the fence has to travel. `SandboxFence` is what travels, and what it leaves
behind is as deliberate as what it carries.

**It carries** the Attempt and NodeRun it belongs to, the lease epoch, and the
fencing token: exactly what a commit needs to prove it is still the current
execution and nothing more.

**It does not carry** the lease's `holder`, `issued_at` or `expires_at`.
Acceptance is explicit that the sandbox receives "only the current fence
identity needed for its work", and those three are not that. `holder` names the
worker that owns the lease, which is operational topology; the timings invite a
sandboxed process to decide for itself whether its lease is still valid, which
is precisely the decision the fence exists to take away from it. Freshness is
adjudicated by the store, against the store's own record, at the moment of the
write.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from maistro.runs.model import TERMINAL_ATTEMPT_STATUSES, Attempt
from maistro.runs.store import StaleExecutionFence

if TYPE_CHECKING:  # pragma: no cover - typing only
    from maistro.runs.model import ExecutionLease
    from maistro.runs.store import RunStore

#: Environment variables a sandboxed process reads its fence from. Prefixed and
#: spelled out rather than packed into one blob so a worker in any language can
#: read them without a parser, which is what "backend-independent" has to mean
#: at the boundary.
ENV_ATTEMPT_ID = "MAISTRO_FENCE_ATTEMPT_ID"
ENV_NODE_RUN_ID = "MAISTRO_FENCE_NODE_RUN_ID"
ENV_LEASE_EPOCH = "MAISTRO_FENCE_LEASE_EPOCH"
ENV_TOKEN = "MAISTRO_FENCE_TOKEN"


@dataclass(frozen=True)
class SandboxFence:
    """The identity a sandboxed worker must present to publish anything."""

    attempt_id: str
    node_run_id: str
    lease_epoch: int
    fencing_token: str

    @classmethod
    def of(cls, lease: ExecutionLease) -> SandboxFence:
        """Project a lease down to what may cross the boundary."""
        return cls(
            attempt_id=lease.attempt_id,
            node_run_id=lease.node_run_id,
            lease_epoch=lease.lease_epoch,
            fencing_token=lease.fencing_token,
        )

    def to_env(self) -> dict[str, str]:
        """The fence as environment, for injection into the sandbox."""
        return {
            ENV_ATTEMPT_ID: self.attempt_id,
            ENV_NODE_RUN_ID: self.node_run_id,
            ENV_LEASE_EPOCH: str(self.lease_epoch),
            ENV_TOKEN: self.fencing_token,
        }

    @classmethod
    def from_env(cls, env: dict[str, str]) -> SandboxFence | None:
        """Read a fence back out of an environment, or `None` if absent.

        Partial is treated as absent rather than reconstructed: a fence missing
        its token is not a weaker fence, it is no fence, and a caller that got
        one anyway would present something the store must reject.
        """
        try:
            return cls(
                attempt_id=env[ENV_ATTEMPT_ID],
                node_run_id=env[ENV_NODE_RUN_ID],
                lease_epoch=int(env[ENV_LEASE_EPOCH]),
                fencing_token=env[ENV_TOKEN],
            )
        except (KeyError, ValueError):
            return None


async def assert_fence_is_current(fence: SandboxFence, *, run_store: RunStore) -> Attempt:
    """Refuse a stale worker before it publishes anything.

    Read from the store rather than compared against anything the caller
    supplied, because the whole point is that the sandboxed worker's view is
    the one under suspicion: it has been running, possibly for a long time,
    possibly through a recovery that reclaimed its lease and started a
    replacement. Its own beliefs about its lease are exactly the evidence that
    cannot be trusted.

    Four ways to be stale, and the first is the one that matters most because
    it is the one a token comparison alone misses.

    **The Attempt is terminal.** Reclaiming an expired lease does *not* clear
    the lease — it cancels the Attempt and leaves the token in place. So a
    worker whose lease lapsed comes back holding a token that still matches,
    and a guard that only compared tokens would wave it through into an
    execution that has already been settled and replaced. Status is checked
    first for exactly that reason.

    The other three are the ordinary ones: the Attempt is gone, a newer lease
    holds it, or the epoch moved — the same staleness caught by number rather
    than by identity, which is what makes a replayed old token visible.
    """
    attempt: Attempt | None = await run_store.get_attempt(fence.attempt_id)
    if attempt is None:
        raise StaleExecutionFence(
            f"Attempt {fence.attempt_id!r} no longer exists; refusing a sandbox commit against it"
        )

    if attempt.status in TERMINAL_ATTEMPT_STATUSES:
        raise StaleExecutionFence(
            f"Attempt {fence.attempt_id!r} is already {attempt.status.value}; it was settled or "
            "reclaimed while the sandbox worker was running, so the worker cannot publish to it"
        )

    lease = attempt.execution_lease
    if lease is None:
        raise StaleExecutionFence(
            f"Attempt {fence.attempt_id!r} holds no execution lease, so a sandbox worker has no "
            "authority to publish to it"
        )
    if lease.fencing_token != fence.fencing_token:
        raise StaleExecutionFence(
            f"Attempt {fence.attempt_id!r} is held by a newer lease; the sandbox worker's fence "
            "was superseded while it was running"
        )
    if lease.lease_epoch != fence.lease_epoch:
        raise StaleExecutionFence(
            f"Attempt {fence.attempt_id!r} is at lease epoch {lease.lease_epoch}, "
            f"but the sandbox worker carries epoch {fence.lease_epoch}"
        )
    return attempt


__all__ = [
    "ENV_ATTEMPT_ID",
    "ENV_LEASE_EPOCH",
    "ENV_NODE_RUN_ID",
    "ENV_TOKEN",
    "SandboxFence",
    "StaleExecutionFence",
    "assert_fence_is_current",
]
