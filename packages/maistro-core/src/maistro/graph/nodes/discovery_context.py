"""Per-cycle discovery context authority (#1051).

Discovery is bounded, per-Workspace work: which sources may be fetched (the
Binding), what the Workspace is watching (topics), what the Persona, durable
user model and current Goals say is relevant right now (context notes), which
candidates were already surfaced (seen fingerprints), and what the discovery
budget still allows. A scheduled Run has no HTTP caller to inject any of
that — the canonical scheduler instantiates the registered template as-is —
so the nodes read it from this authority, wired by the host's node resolver
the same way ``effect_context`` is.

The Protocol is the seam; the host (Hive's ``services.discovery``)
implements it over its own durable config/budget/ledger stores and the
canonical user-model and Goal services. The bare default provides nothing:
nodes run context-free for tests and non-Hive composition, and a cycle
without a wired provider still executes its deterministic pipeline with
whatever the template's own inputs carry — the authority widens what a
cycle *knows*, never what it may *do* (fetches stay Binding-gated; model
calls stay governed-egress-gated).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class DiscoveryBudgetExhausted(RuntimeError):
    """The Workspace's discovery budget for the period is spent.

    Raised by the host's budget gate *before* any physical work of that kind
    starts, so a scheduled discovery Run ends as an honest refusal recorded
    on the Run instead of new fetches or model calls.
    """


@dataclass(frozen=True)
class DiscoveryCycleContext:
    """Everything one discovery cycle needs besides its node inputs.

    ``source_binding_id`` / ``curator_binding_id`` are the Workspace's
    pre-authorized Binding ids recorded at configuration time; nodes fall
    back to them when their own ``binding_id`` input is empty, which is how a
    scheduled fire (no HTTP caller) still resolves the right Bindings.
    """

    watch_topics: tuple[str, ...] = ()
    context_notes: tuple[str, ...] = ()
    seen_fingerprints: frozenset[str] = field(default_factory=frozenset)
    category_downweights: tuple[tuple[str, float], ...] = ()
    source_binding_id: str = ""
    curator_binding_id: str = ""
    curator_model: str = ""
    max_candidates: int = 0
    max_surfaced: int = 0
    min_scout_score: float = -1.0
    #: Set when the host refuses the whole cycle before any node runs; the
    #: fetch node surfaces it as its output ``refusal`` and the run's curator
    #: stage records nothing. Budget gate is checked per kind: ``fetch`` /
    #: ``curate`` name the gate that closed.
    budget_refusal: str = ""


class DiscoveryContextProvider(Protocol):
    """The host-implemented read for one Workspace's discovery cycle state."""

    async def context_for(
        self, workspace_id: str, project_id: str, user_id: str
    ) -> DiscoveryCycleContext: ...


class _BareProvider:
    """Context-free default: no topics, no ledger, no Binding ids, no budget."""

    async def context_for(
        self, workspace_id: str, project_id: str, user_id: str
    ) -> DiscoveryCycleContext:
        return DiscoveryCycleContext()


def default_discovery_context() -> DiscoveryContextProvider:
    return _BareProvider()


__all__ = [
    "DiscoveryBudgetExhausted",
    "DiscoveryContextProvider",
    "DiscoveryCycleContext",
    "default_discovery_context",
]
