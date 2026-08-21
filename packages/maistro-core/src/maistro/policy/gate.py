"""Bridge the policy engine to the harness ``ActionGate`` shape (SPEC-208 tie-in).

``PolicyActionGate`` satisfies the ``ActionGate`` protocol used by
``SafeHarnessRunner`` *structurally* — it exposes ``async def allow(action)`` and
imports nothing from the capabilities layer, so the policy package stays
lower-level and dependency-light. It maps a harness action dict onto a policy
:class:`Action` and charges it against the engine; only ALLOW permits the action.
"""

from __future__ import annotations

import math
from typing import Any

from maistro.policy.engine import SequencePolicyEngine
from maistro.policy.types import Action


def _as_number(value: Any) -> float:
    """Coerce a charge value from the foreign harness's action envelope.

    Clamped to finite, non-negative: these numbers debit cumulative budgets,
    so a provider reporting a negative token count would *credit* the session,
    and a NaN cost poisons every later ``value > limit`` comparison (NaN
    compares False), silently disabling BudgetRule enforcement. Malformed or
    hostile values charge zero — the action is still recorded, just never
    allowed to widen the budget.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number) or number < 0:
        return 0.0
    return number


class PolicyActionGate:
    def __init__(
        self,
        engine: SequencePolicyEngine,
        *,
        key: str,
        kind_field: str = "tool",
    ) -> None:
        self._engine = engine
        self._key = key
        self._kind_field = kind_field

    async def allow(self, action: dict[str, Any]) -> bool:
        act = Action(
            kind=str(action.get(self._kind_field, "unknown")),
            tokens=int(_as_number(action.get("tokens", 0))),
            cost=_as_number(action.get("cost", 0)),
            seconds=_as_number(action.get("seconds", 0)),
            metadata=action,
        )
        return self._engine.charge(self._key, act).allowed
