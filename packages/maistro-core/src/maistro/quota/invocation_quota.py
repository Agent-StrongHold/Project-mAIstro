"""Invocation-scoped quota contracts, not another provider execution authority.

The trusted composition root resolves the principal from the canonical Run and
bounds from an adapter that enforces those bounds on its physical request. Never
resolve identity, limits, or exemption from untrusted request fields. An estimate
is not an enforceable provider maximum by itself; overages remain real spend.

SQLite implementation: :mod:`maistro.quota.sqlite_invocation_quota`. This slice
is opt-in pending canonical backend composition, PostgreSQL parity, and audited
opening balances. The legacy tracker is not an input to enforcement.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from maistro.capabilities.binding import Binding
    from maistro.capabilities.invocation import Invocation

QuotaUnit = Literal["tokens", "micro_usd", "requests"]
Outcome = Literal["completed", "not_applied", "unknown"]
SQLITE_MAX_INTEGER = (1 << 63) - 1


def require_identifier(value: str, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty")


def require_amount(value: int, name: str) -> None:
    if type(value) is not int or not 0 <= value <= SQLITE_MAX_INTEGER:
        raise ValueError(f"{name} must be a nonnegative signed-64-bit integer")


@dataclass(frozen=True)
class QuotaBudget:
    """Immutable, explicitly initialized budget for the half-open [start, end) period.

    None on a scope selector means all values. All matching budgets apply, not
    just the most specific one. ``reserve`` is protected headroom, so the usable
    ceiling is ``limit - reserve``. A new policy version needs a new budget_id.
    ``opening_spend`` must include verified prior/ambient spend; coverage_ref is
    an operator's evidence reference, not a claim that this class verified it.
    """

    budget_id: str
    unit: QuotaUnit
    limit: int
    period_start: int
    period_end: int
    coverage_ref: str
    opening_spend: int
    reserve: int = 0
    provider_name: str | None = None
    workspace_id: str | None = None
    principal_id: str | None = None
    capability: str | None = None

    def __post_init__(self) -> None:
        require_identifier(self.budget_id, "budget_id")
        require_identifier(self.coverage_ref, "coverage_ref")
        if self.unit not in {"tokens", "micro_usd", "requests"}:
            raise ValueError("unknown quota unit")
        for name in ("limit", "reserve", "opening_spend", "period_start", "period_end"):
            require_amount(getattr(self, name), name)
        if self.reserve > self.limit or self.period_start >= self.period_end:
            raise ValueError("invalid reserve or billing period")
        for name in ("provider_name", "workspace_id", "principal_id", "capability"):
            value = getattr(self, name)
            if value is not None:
                require_identifier(value, name)


@dataclass(frozen=True)
class QuotaEstimate:
    """Host-resolved identity and upper bounds for this single physical Invocation."""

    principal_id: str
    tokens: int | None = None
    micro_usd: int | None = None

    def __post_init__(self) -> None:
        require_identifier(self.principal_id, "principal_id")
        for name in ("tokens", "micro_usd"):
            value = getattr(self, name)
            if value is not None:
                require_amount(value, name)

    def maximum(self, unit: str) -> int | None:
        if unit == "requests":
            return 1
        if unit == "tokens":
            return self.tokens
        if unit == "micro_usd":
            return self.micro_usd
        raise ValueError("unknown quota unit")


EstimateResolver = Callable[["Invocation", "Binding"], Awaitable[QuotaEstimate]]


@dataclass(frozen=True)
class QuotaObservation:
    """An absolute, versioned observation, never an additive usage delta.

    Revision zero belongs to the canonical Invocation terminal record. Positive
    revisions are for a trusted provider/administrative reconciliation adapter.
    Missing dimensions remain held; later revisions cannot erase a measurement
    by substituting None. Corrections may reduce spend only with a newer revision.
    """

    invocation_id: str
    provider_name: str
    evidence_id: str
    revision: int
    outcome: Outcome
    tokens: int | None = None
    micro_usd: int | None = None

    def __post_init__(self) -> None:
        for name in ("invocation_id", "provider_name", "evidence_id"):
            require_identifier(getattr(self, name), name)
        require_amount(self.revision, "revision")
        if self.outcome not in {"completed", "not_applied", "unknown"}:
            raise ValueError("invalid provider outcome")
        for name in ("tokens", "micro_usd"):
            value = getattr(self, name)
            if value is not None:
                require_amount(value, name)
        if self.outcome != "completed" and (self.tokens is not None or self.micro_usd is not None):
            raise ValueError("usage needs a confirmed completed outcome")

    def actual(self, unit: str) -> int | None:
        if self.outcome == "not_applied":
            return 0
        if self.outcome == "unknown":
            return None
        if unit == "requests":
            return 1
        if unit == "tokens":
            return self.tokens
        if unit == "micro_usd":
            return self.micro_usd
        raise ValueError("unknown quota unit")

    def payload(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class QuotaBalance:
    budget_id: str
    ceiling: int
    spent: int
    held: int

    @property
    def available(self) -> int:
        # Negative availability is truthful provider overage, not clamped away.
        return self.ceiling - self.spent - self.held


class InvocationQuotaDenied(RuntimeError):
    """No quota policy, an unbounded request, or insufficient remaining budget."""


class QuotaEvidenceConflict(RuntimeError):
    """A reservation/evidence identity was reused with different facts."""
