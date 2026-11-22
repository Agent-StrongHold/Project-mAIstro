"""Bounded execution-budget policy for declared DAG/Graph configuration.

This module is the single authority that turns *declared* execution-budget
configuration (DAG cycle bounds, per-node timeouts) into the *effective*
values the canonical executor enforces. It exists because the shipped
``DAGFile.max_cycles`` field and per-node ``config`` timeouts were accepted by
product surfaces while execution ignored them (#1184): a value is either an
authoritative input to this policy or it is not part of the supported
contract — there is no third state where a field looks operational and does
nothing.

The contract, in one place:

- **Cycles.** A declared cycle budget is the number of traversal frontiers
  (activation waves) the durable walk may execute — the incumbent
  ``GraphConfig.max_cycles`` semantics, enforced fail-closed: exhausting it
  fails the Run with the budget named rather than truncating silently. Valid
  numbers clamp into ``[MIN_DAG_CYCLES, MAX_DAG_CYCLES]``, the same envelope
  ``GraphConfig.max_cycles`` already publishes. A declared value that cannot
  be parsed resolves to ``MIN_DAG_CYCLES``: a cap that cannot be read must buy
  the tightest bound, never the loosest. An *undeclared* budget (no value)
  means the platform floors (``max_steps`` and the per-node visit budget)
  remain the only bounds; canonical Graphs do not declare one today, so their
  behavior is unchanged. Because the budget counts waves, a DAG whose linear
  depth exceeds its declared budget now fails with the shortfall named — the
  honest reading of the field the surfaces already advertise, and the reason
  shipped DAG data declares budgets that cover its own depth.

- **Node timeouts.** A declared ``timeout_s`` is resolved through the clamp
  into ``[MIN_NODE_TIMEOUT_S, MAX_NODE_TIMEOUT_S]`` and becomes the canonical
  ``ExecutionRuntime`` deadline for that node's Attempt: the runtime enforces
  it, the Attempt records ``deadline_at`` and settles ``TIMED_OUT`` on expiry.
  The durable walker applies the resolved value at the Attempt boundary, so a
  product runner's own hard-coded transport timeout can never extend work past
  the canonical deadline — it can only be the same number or lose the race.
  An undeclared timeout means no Attempt deadline (today's behavior for every
  canonical node kind); a *declared but unparseable* value resolves to
  ``DEFAULT_NODE_TIMEOUT_S`` — the incumbent deadline — because a garbage
  deadline must not terminate legitimate work early.

Clamping — never rejecting — is deliberate for data that predates the policy
(stored Hive DAGs, evolved genomes): rejecting would strand previously-valid
product data at read time. Both the declared and the effective value are
recorded on the Graph/Run so a clamped value is visible, not silent.
"""

from __future__ import annotations

from typing import Any

#: Envelope for declared DAG cycle budgets. ``MAX_DAG_CYCLES`` matches
#: ``GraphConfig.max_cycles``'s upper bound so both DAG dialects advertise one
#: loop envelope.
MIN_DAG_CYCLES = 1
MAX_DAG_CYCLES = 20

#: The incumbent per-call timeout the legacy Hive node adapter hard-coded
#: before budgets became policy. It remains the default deadline for nodes
#: that declare nothing, and the resolution of a declared-but-unparseable
#: timeout — the incumbent behavior is the safe fallback for an unreadable
#: deadline.
DEFAULT_NODE_TIMEOUT_S = 120.0

#: Envelope for declared per-node timeouts. The floor keeps a typo from
#: failing work before it starts; the ceiling keeps one declared value from
#: holding a frontier hostage far past any interactive contract.
MIN_NODE_TIMEOUT_S = 1.0
MAX_NODE_TIMEOUT_S = 600.0

_TIMEOUT_KEY = "timeout_s"
_CYCLES_KEY = "max_cycles"


def _declared_number(declared: Any) -> float | None:
    """Return the declared value as a finite number, or None if unreadable.

    Bools are rejected even though ``isinstance(True, int)``: a flag is not a
    budget. NaN and infinities are unreadable for the same reason a string is.
    """
    if isinstance(declared, bool) or declared is None:
        return None
    if isinstance(declared, (int, float)):
        value = float(declared)
    elif isinstance(declared, str):
        try:
            value = float(declared.strip())
        except ValueError:
            return None
    else:
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def resolve_max_cycles(declared: Any) -> int:
    """Resolve a declared DAG cycle budget to its effective, bounded value.

    Valid numbers clamp into ``[MIN_DAG_CYCLES, MAX_DAG_CYCLES]``; anything
    unreadable resolves to ``MIN_DAG_CYCLES`` (see module docstring). Never
    raises: stored product data must keep running under the clamp.
    """
    value = _declared_number(declared)
    if value is None:
        return MIN_DAG_CYCLES
    return max(MIN_DAG_CYCLES, min(int(value), MAX_DAG_CYCLES))


def resolve_node_timeout_s(
    declared: Any,
    *,
    default: float = DEFAULT_NODE_TIMEOUT_S,
) -> float:
    """Resolve a declared per-node timeout to its effective, bounded seconds.

    Valid positive numbers clamp into ``[MIN_NODE_TIMEOUT_S,
    MAX_NODE_TIMEOUT_S]``; non-positive or unreadable values resolve to the
    incumbent ``default``. Never raises: stored product data must keep running
    under the clamp.
    """
    value = _declared_number(declared)
    if value is None or value <= 0:
        return default
    return max(MIN_NODE_TIMEOUT_S, min(value, MAX_NODE_TIMEOUT_S))


def declared_node_timeout_s(policies: Any) -> float | None:
    """Read a node's declared timeout from canonical ``Node.policies``.

    Returns None when the node declares nothing — the "policy does not
    participate" state — and the resolved (bounded) value otherwise, so the
    walker can hand the exact deadline it will enforce to the node contract.
    """
    if not isinstance(policies, dict) or policies.get(_TIMEOUT_KEY) is None:
        return None
    return resolve_node_timeout_s(policies.get(_TIMEOUT_KEY))


def declared_dag_max_cycles(metadata: Any) -> int | None:
    """Read a graph's declared cycle budget from canonical ``Graph.metadata``.

    Accepts either spelling a Graph author may produce: the raw declaration
    (``max_cycles``) or the adapter-recorded pair's effective half
    (``max_cycles_effective``). Returns None when the graph declares nothing —
    the platform floors remain the only bounds — and the resolved (bounded)
    budget otherwise.
    """
    if not isinstance(metadata, dict):
        return None
    if metadata.get(_CYCLES_KEY) is not None:
        return resolve_max_cycles(metadata.get(_CYCLES_KEY))
    if metadata.get("max_cycles_effective") is not None:
        return resolve_max_cycles(metadata.get("max_cycles_effective"))
    return None


__all__ = [
    "DEFAULT_NODE_TIMEOUT_S",
    "MAX_DAG_CYCLES",
    "MAX_NODE_TIMEOUT_S",
    "MIN_DAG_CYCLES",
    "MIN_NODE_TIMEOUT_S",
    "declared_dag_max_cycles",
    "declared_node_timeout_s",
    "resolve_max_cycles",
    "resolve_node_timeout_s",
]
