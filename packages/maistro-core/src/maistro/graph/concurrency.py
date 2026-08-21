"""Bounds how many LLM calls a graph execution can have in flight at once.

The problem
-----------
Graph execution fans out twice, and the two multiply:

* ``run.py`` gathers every active role in a cycle — unbounded in the number of
  roles;
* ``node.py`` gathers ``beam_width`` attempts inside each of those roles —
  unbounded in the beam width.

Neither had a cap, so a wide cycle over a wide beam opened roles x beam_width
concurrent LLM calls with nothing in the middle to say no. A 300-node DAG was
enough to push interactive chat p50 from 2.03s to 4.06s purely by crowding it
out.

Where the bound belongs
-----------------------
Not on either gather. Bounding both would nest — a role would hold a permit
while its own beam attempts waited for permits from the same pool, which
deadlocks as soon as the pool is smaller than the fan-out.

So the gate sits at the *leaf*: the two places that actually invoke
``llm_call`` (``_execute_single`` and ``_beam_attempt``). Every concurrent call
passes through exactly one permit, whatever shape the fan-out above it takes,
and there is no nesting to deadlock.

Why a LaneGate rather than a semaphore
--------------------------------------
Graph work is ``BACKGROUND``: it is exactly the batch traffic that a reserved
``LIVE`` floor exists to keep away from interactive requests. Using the same
gate type as the task runner means a graph run cannot starve chat, and the two
subsystems describe their scheduling in one vocabulary instead of two.

This is a ceiling, not a throttle — see `maistro.http` for why sizing a shared
resource down to shed load is the worst of the available options.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from maistro.tasks.lanes import Lane, LaneGate

# Concurrent LLM calls allowed across all graph runs in this process.
#
# Sized from Little's Law: at ~2s per call, 32 permits sustains ~16 calls/s of
# graph work. Generous enough that ordinary DAGs never touch it, low enough
# that a runaway fan-out cannot exhaust the HTTP pool or the provider's rate
# limit before anything else notices.
DEFAULT_MAX_CONCURRENT_LLM_CALLS = 32

# LIVE keeps a floor even here: a graph node tagged interactive (a human
# waiting on a single node re-run) should not queue behind a batch sweep.
DEFAULT_LIVE_RESERVED = 4

_gate: LaneGate | None = None


def configure_graph_concurrency(
    *,
    max_concurrent_llm_calls: int = DEFAULT_MAX_CONCURRENT_LLM_CALLS,
    live_reserved: int = DEFAULT_LIVE_RESERVED,
) -> None:
    """Resize the gate. Call during startup, before the first graph run.

    Floors are clamped so one permit always stays shared. `LaneGate` refuses a
    configuration where a lane has neither a floor nor a shared permit — that
    is a deadlock, not a throttle — and a caller asking for a small total
    should get a working gate rather than an exception.
    """
    global _gate
    shareable = max(0, max_concurrent_llm_calls - 1)
    live = min(live_reserved, shareable)
    background = min(1, max(0, shareable - live))
    _gate = LaneGate(
        max_concurrent_llm_calls,
        live_reserved=live,
        background_reserved=background,
    )


def get_graph_gate() -> LaneGate:
    """The process-wide graph LLM gate, created on first use."""
    global _gate
    if _gate is None:
        configure_graph_concurrency()
    assert _gate is not None
    return _gate


@asynccontextmanager
async def llm_call_permit(lane: Lane = Lane.BACKGROUND, tier: str = "P2") -> AsyncIterator[None]:
    """Hold a permit for the duration of one LLM call.

    Wraps the call itself rather than the fan-out above it, so the bound holds
    no matter how the role and beam gathers multiply, and nothing nests.
    """
    async with get_graph_gate().hold(lane, tier):
        yield
