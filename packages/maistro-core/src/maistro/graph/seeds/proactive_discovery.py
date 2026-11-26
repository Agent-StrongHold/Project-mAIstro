"""`proactive-discovery` — the bounded discovery cycle seed (#1051).

The physical work of one discovery cycle as a canonical DAG of registered
kinds — fetch (governed egress), scout (cheap deterministic tier), curate
(stronger tier) — so a Schedule can fire it while the user is away and the
Run carries the same provenance, budget and recovery semantics as foreground
work. There is deliberately no private crawler loop behind this: the seed's
node caps, the Workspace's durable budgets, and the Binding's declared
sources are the only ways work enters the cycle.

Per-Workspace inputs (Binding ids, caps, watch topics, fresh Persona/user-
model/Goal context) arrive through the ``discovery_context`` authority at
execution time — a scheduled fire has no HTTP caller, so the host's node
resolver wires it exactly like ``effect_context``. The template itself stays
content-identical across Workspaces, which is what lets the scheduler prime
it into the canonical template store once and reuse it.
"""

from __future__ import annotations

from typing import Any


def proactive_discovery_seed() -> dict[str, Any]:
    """Return a fresh proactive-discovery DAG spec.

    Binding ids and cycle caps default empty: an unconfigured Workspace
    refuses at the fetch node (BindingNotFound) instead of fetching anything.
    """
    return {
        "id": "proactive-discovery",
        "name": "Proactive Discovery",
        "description": (
            "Bounded proactive discovery cycle (#1051): fetch the sources the "
            "Workspace's discovery Binding declares through governed egress, "
            "scout candidates deterministically (dedupe, watch topics, "
            "feedback down-weights), then curate a small surfaced set with "
            "Persona + user-model + Goal context. Home/Waiting surfacing "
            "happens in the Workspace layer, never by interrupting."
        ),
        "use_case": "workspace_agent",
        # The declared cycle budget must cover the seed's own depth: three
        # sequential nodes are three traversal waves under the enforced budget
        # contract (maistro.graph.policies).
        "max_cycles": 3,
        "nodes": [
            {
                "id": "discovery_fetch",
                "kind": "discovery.source_fetch",
                "inputs": {
                    # Resolved from the discovery context authority when empty,
                    # so a scheduled fire needs no caller-supplied ids.
                    "binding_id": "",
                    "max_entries_per_source": 20,
                    "max_age_hours": 72,
                    "limit": 30,
                    "timeout_s": 15.0,
                },
            },
            {
                "id": "discovery_scout",
                "kind": "discovery.scout",
                "inputs": {
                    "watch_topics": [],
                    "min_score": 0.1,
                    "max_candidates": 24,
                },
            },
            {
                "id": "discovery_curate",
                "kind": "discovery.curate",
                "inputs": {
                    "context_notes": [],
                    "strategy": "model",
                    # Empty resolves at execution: the Workspace's configured
                    # curator alias via the discovery context, else the node
                    # default — so config changes apply without editing the
                    # content-identical template.
                    "model": "",
                    "binding_id": "",
                    "max_surfaced": 3,
                    "min_confidence": 0.3,
                    "timeout_s": 30.0,
                },
            },
        ],
        "edges": [
            {"from_node": "discovery_fetch", "to_node": "discovery_scout"},
            {"from_node": "discovery_scout", "to_node": "discovery_curate"},
        ],
        "entry_node": "discovery_fetch",
    }


__all__ = ["proactive_discovery_seed"]
