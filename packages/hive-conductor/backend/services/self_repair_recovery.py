"""Recovery and wakeup for self-repair approval Runs (#2405, M1-B8 audit 2).

The self-repair provider's approval-gated remediations park as durable
one-node Graphs with ``admission_source=self_repair``. Two coordination
defects made those waits inert without an owned recovery category:

1. An *answered* Run was queued by the canonical HITL door, but no shipped
   consumer owned the ``self_repair`` admission source, so the approved
   effect never dispatched — an approval appeared accepted while the real
   action never happened.
2. A process killed between ``create_run`` and the durable continuation's
   first checkpoint stranded the claimed canonical Run: no continuation, no
   recovery owner.

This module owns both halves through the *existing* canonical Graph seams —
it is not a scheduler and owns no execution lifecycle. ``recover_queued_graph_runs``
reconciles checkpoint-1 crash windows (and queued-after-answer Runs) from
durable Run facts; ``resume_due_graph_runs`` fences lease-expired attempts
and wakes durable continuations. The Attempt lease and fence remain the sole
authorities for whether physical work may start, so at most one physical
Attempt per Run ever dispatches — including across replicas.
"""

from __future__ import annotations

from typing import Any

from maistro.graph.durable_runs import (
    NodeResolver,
    recover_queued_graph_runs,
    resume_due_graph_runs,
)
from maistro.runs.model import Run
from services.dag_agents import _container, _resolve_nodes_with
from services.scan_continuations import scan_continuation

_SOURCE = "self_repair"
# None is the pre-restart admission shape (the admitting process named no
# executor); "durable_graph" is what `admit_self_repair_approval` stamps.
_EXECUTORS = frozenset({None, "durable_graph"})


def _owned(run: Run) -> bool:
    return (
        run.provenance.get("admission_source") == _SOURCE
        and run.provenance.get("executor") in _EXECUTORS
    )


def _resolver(run: Run) -> NodeResolver:
    # The resolver the admitting path used: which node kinds may execute is
    # the Run's graph snapshot, and their authorities are the Container's.
    # `infra.approval_gated_action` composes from the durable Binding
    # reference + live effect/registry authorities, so an answered Run
    # resumes without any serialized Python closure (#2405).
    del run
    return _resolve_nodes_with()


async def recover_stranded_self_repair_runs(*, limit: int = 100) -> int:
    """Resume QUEUED self-repair approval Runs no caller is carrying.

    Covers both stranded shapes: the crash window between canonical Run
    admission and the first durable checkpoint (rebuilt from the admitted
    launch snapshot), and the queued-after-answer continuation the HITL door
    left for exactly this recovery owner.
    """
    container = _container()
    if container is None or container.graph_run_store is None:
        return 0
    return await recover_queued_graph_runs(
        store=container.graph_run_store,
        run_store=container.run_store,
        node_resolver_factory=_resolver,
        eligible=_owned,
        admission_source=_SOURCE,
        events=_canonical_recovery_events(container),
        limit=limit,
        # Held across ticks: the scan is bounded per call, and only a tick
        # that resumes where the last stopped crosses a foreign-owned QUEUED
        # prefix longer than that bound (#1127).
        scan=scan_continuation("recover_queued_self_repair_runs", container.run_store),
    )


async def wake_due_self_repair_runs(*, limit: int = 100) -> int:
    """Resume self-repair continuations whose lease fence or timer allows it.

    A worker crash mid-effect leaves the Attempt's lease un-renewed; the
    canonical fence — not this tick — decides whether physical work may
    start again, so an ambiguous external effect is never blindly replayed.
    """
    container = _container()
    if container is None or container.graph_run_store is None:
        return 0
    return await resume_due_graph_runs(
        store=container.graph_run_store,
        run_store=container.run_store,
        node_resolver_factory=_resolver,
        eligible=_owned,
        events=_canonical_recovery_events(container),
        limit=limit,
        scan=scan_continuation("resume_due_self_repair_runs", container.graph_run_store),
    )


def _canonical_recovery_events(container: Any) -> Any:
    """Route recovery facts through the Container's canonical Event publisher."""
    from maistro.events.publisher import CanonicalEventPublisher
    from maistro.runs.recovery_events import CanonicalRecoveryEventSink

    publisher = container.canonical_event_publisher
    if not isinstance(publisher, CanonicalEventPublisher):
        raise RuntimeError("canonical recovery Event publisher is not configured")
    return CanonicalRecoveryEventSink(container.run_store, publisher)


__all__ = ["recover_stranded_self_repair_runs", "wake_due_self_repair_runs"]
