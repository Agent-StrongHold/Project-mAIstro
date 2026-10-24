"""Bounded frontier-model RSI campaigns (M5-B, #114).

A campaign is a deliberately ceilinged experiment: it runs a pool of
objectives through one *frontier* arm and one cheaper-router *baseline* arm
over the canonical LiteLLM gateway, and answers one question — what does RSI
find when model capability is not the primary constraint? Cheap/free routing
stays the idle floor (see ``quota_burn``); it is not the experimental
ceiling, so an operator may point the frontier arm at a stronger model.

The harness adds no execution authority of its own. The canonical execution
model stays ``Goal -> Graph -> Run -> NodeRun -> Attempt``; a campaign maps
onto those axes read-only (campaign run id -> arm/objective node scope ->
attempt ordinal) and adds exactly one thing: every model call it dispatches
traverses the canonical Invocation seam —
``maistro.capabilities.invocation.Invocation`` persisted in an
``InvocationStore``, usage/cost attributed per ADR-081226-6b46, and charged
exactly once to the quota ledger through
``maistro.quota.recorder.CanonicalInvocationUsageRecorder`` — the same
terminalization hook canonical model effects use. Missing provider usage is
absent evidence, never a measured zero (#718).

Campaigns stop mechanically. ``CampaignCeilings`` must set at least one
explicit ceiling (spend, token quota, model-call quota, wall clock, objective
count, or work scope); :func:`ensure_bounded` refuses an unbounded policy
wherever a budget is kept, ``BudgetState`` is checked before every attempt
and inside the dispatch seam, so a ceiling already reached refuses new work
instead of merely being reported afterwards.
"""

from __future__ import annotations

import asyncio
import posixpath
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Protocol

import structlog
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from maistro.capabilities.binding import ResolvedBinding
from maistro.capabilities.invocation import (
    EffectNotApplied,
    InMemoryInvocationStore,
    Invocation,
    InvocationStatus,
    InvocationUsage,
)
from maistro.capabilities.providers.llm_gateway import MODEL_CHAT_CAPABILITY
from maistro.providers.types import ModelMetadata, compute_cost_cents
from maistro.quota.recorder import CanonicalInvocationUsageRecorder
from maistro.quota.usage_log import InMemoryUsageLog
from maistro.quota.usage_report import reported_usage

logger = structlog.get_logger()

__all__ = [
    "ArmPolicy",
    "ArmResult",
    "BudgetExhausted",
    "BudgetState",
    "CampaignCeilings",
    "CampaignReport",
    "ModelCall",
    "ModelCallResult",
    "Objective",
    "ObjectivePool",
    "StopReason",
    "gateway_model_call",
    "keyword_objective_scorer",
    "run_campaign",
]


# -- ceilings ----------------------------------------------------------------

#: A non-empty string, stripped. Declarative pydantic constraint: refusing
#: blank identifiers/tasks/paths needs no validator method.
NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class CampaignCeilings(BaseModel):
    """The explicit bounds a campaign may never exceed.

    Every field is an operator-supplied ceiling; ``None`` means "this axis is
    unbounded", but *at least one* axis must be bounded —
    :func:`ensure_bounded` refuses an unbounded policy at every point a
    budget is kept or a campaign is admitted (never discovered at spend
    time). Work scope bounds what experiment prompts may name:
    ``allowed_paths`` limits the path prefixes objectives may reference
    (empty means every path is in scope), ``max_objectives`` bounds how many
    pool entries may be attempted.
    """

    model_config = ConfigDict(extra="forbid")

    #: The float ceilings also refuse non-finite values: ``inf`` (which the
    #: CLI's argparse layer happily parses out of ``--max-seconds inf``) is
    #: greater than zero, so it would pass a bare ``gt=0`` and read as a
    #: bounded axis whose stop condition can never fire — a campaign
    #: admitted on it as the sole ceiling would run the whole pool. NaN
    #: fails every comparison the same way. Bounded means reachable.
    max_spend_usd: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    max_total_tokens: int | None = Field(default=None, gt=0)
    max_model_calls: int | None = Field(default=None, gt=0)
    max_wall_clock_s: float | None = Field(default=None, gt=0, allow_inf_nan=False)
    max_objectives: int | None = Field(default=None, gt=0)
    allowed_paths: tuple[NonEmptyStr, ...] = ()

    @property
    def is_bounded(self) -> bool:
        """True when at least one ceiling axis is set."""
        return bool(self.allowed_paths) or any(
            bound is not None
            for bound in (
                self.max_spend_usd,
                self.max_total_tokens,
                self.max_model_calls,
                self.max_wall_clock_s,
                self.max_objectives,
            )
        )


def ensure_bounded(ceilings: CampaignCeilings) -> None:
    """Refuse an unbounded campaign policy.

    Called wherever a ceiling policy is turned into enforcement (a
    ``BudgetState``) or admitted for a run, so no code path can start a
    campaign whose operator supplied no ceiling.
    """
    if not ceilings.is_bounded:
        raise ValueError(
            "a campaign must set at least one explicit ceiling "
            "(spend, tokens, model calls, wall clock, objectives, or allowed paths)"
        )


class StopReason(BaseModel):
    """Why a campaign stopped, and which ceiling fired."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ceiling: str
    observed: float
    limit: float
    #: True when the stop fired on *absent evidence* rather than a reached
    #: value: the declared ceiling is measured from usage the provider (or
    #: the operator's pricing table) never reported, so its counter can
    #: never advance and the campaign fails closed instead of running on.
    evidence_missing: bool = False

    @property
    def message(self) -> str:
        if self.evidence_missing:
            return (
                f"ceiling {self.ceiling!r} unenforceable: measured evidence "
                f"is absent (observed {self.observed}, limit {self.limit})"
            )
        return f"ceiling {self.ceiling!r} reached: {self.observed} >= {self.limit}"


# -- objective pool ----------------------------------------------------------


class Objective(BaseModel):
    """One unit of campaign work: a task spec plus its scope declaration.

    ``paths`` names the file areas the objective's work may touch; a pool
    entry referencing paths outside the campaign's ``allowed_paths`` is
    refused at admission and never dispatched.
    """

    model_config = ConfigDict(extra="forbid")

    objective_id: NonEmptyStr
    task: NonEmptyStr
    #: Keywords share the non-empty, whitespace-stripped constraint applied to
    #: ids and tasks: an empty keyword is a substring of every response, so it
    #: would score a perfect match (and verified progress) with no work done.
    keywords: tuple[NonEmptyStr, ...] = ()
    paths: tuple[str, ...] = ()


class ObjectivePool(BaseModel):
    """The frozen, ordered objective pool both campaign arms run.

    The pool is constructed once and shared: the frontier arm and the
    baseline arm iterate the identical sequence, so an arm-to-arm comparison
    can never be confounded by differing objective sets.
    """

    model_config = ConfigDict(extra="forbid")

    objectives: tuple[Objective, ...]


def ensure_unique_objectives(pool: ObjectivePool) -> None:
    """Refuse an empty pool or duplicate objective ids.

    Called where a pool is admitted for a run (and by the CLI before it
    builds arms), so two arms can never silently score the same objective id
    twice or compare against an empty record.
    """
    if not pool.objectives:
        raise ValueError("an objective pool cannot be empty")
    ids = [objective.objective_id for objective in pool.objectives]
    if len(ids) != len(set(ids)):
        raise ValueError("objective ids must be unique within a pool")


def ensure_unique_arm_ids(arms: Sequence[ArmPolicy]) -> None:
    """Refuse duplicate arm ids.

    Ledgers, budgets, and ordinals are keyed by arm_id, so a repeated id
    would collapse two arms into one shared state and collide their
    binding/invocation identities. Rejected at admission, before any
    ledger is built.
    """
    ids = [arm.arm_id for arm in arms]
    if len(ids) != len(set(ids)):
        raise ValueError("arm ids must be unique within a campaign")


def keyword_objective_scorer(objective: Objective, response: str) -> float:
    """Harness-grade deterministic score: the fraction of objective keywords
    the response contains.

    Real benchmark-graded pools plug a benchmark runner in via ``scorer=``;
    this default exists so a campaign is scoreable end-to-end without one.
    A pool with no keywords scores 1.0 on any non-empty response — presence
    of work, not quality.
    """
    if not objective.keywords:
        return 1.0 if response.strip() else 0.0
    lowered = response.lower()
    hits = sum(1 for keyword in objective.keywords if keyword.lower() in lowered)
    return hits / len(objective.keywords)


# -- model call seam ---------------------------------------------------------


class ModelCallResult(BaseModel):
    """What one model call returned, with the usage the provider reported.

    ``usage_reported=False`` means the provider sent no usable usage object —
    recorded downstream as unreported evidence, never as zero (#718).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    content: str
    input_tokens: int = 0
    output_tokens: int = 0
    usage_reported: bool = False
    model_version: str = ""


class ModelCall(Protocol):
    """Async transport seam: dispatch one chat completion."""

    async def __call__(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> ModelCallResult: ...


def gateway_model_call(model: str, *, timeout: float = 60.0) -> ModelCall:
    """Build a ``ModelCall`` routing ``model`` through the LiteLLM gateway.

    Thin composition over ``gateway.make_gateway_llm_call``: the gateway
    callable stays the transport; the ``on_response`` seam captures the raw
    body so reported usage and the concrete served model version survive
    into the canonical Invocation.
    """

    from maistro_rsi.gateway import make_gateway_llm_call

    captured: dict[str, Any] = {}

    def _on_response(body: dict[str, object], _response: object) -> None:
        captured["body"] = body

    inner = make_gateway_llm_call(model, timeout=timeout, on_response=_on_response)

    async def call(
        messages: list[dict[str, str]],
        *,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> ModelCallResult:
        content = await inner(messages, temperature=temperature, max_tokens=max_tokens)
        body = captured.get("body")
        reported = reported_usage(body) if isinstance(body, dict) else None
        return ModelCallResult(
            content=content,
            input_tokens=reported[0] if reported else 0,
            output_tokens=reported[1] if reported else 0,
            usage_reported=reported is not None,
            model_version=str(body.get("model") or "") if isinstance(body, dict) else "",
        )

    return call


# -- budget ledger -----------------------------------------------------------


class BudgetExhausted(RuntimeError):
    """A ceiling is already reached; dispatching more work is refused."""

    def __init__(self, stop: StopReason) -> None:
        super().__init__(stop.message)
        self.stop = stop


class BudgetState:
    """Observed consumption against the ceilings, with mechanical enforcement.

    Counters are charged from measured Invocation usage only. Enforcement is
    two-sided: ``stop_reason`` stops *new* attempts once a ceiling is reached
    (the Q3 semantics the canonical workspaces campaigns use), and
    ``admit_call`` — called inside the dispatch seam — raises
    :class:`BudgetExhausted` rather than letting an already-spent campaign
    dispatch another model call. Spend/tokens are measured post-hoc, so a
    ceiling can be crossed by at most the one in-flight call; the call-count
    ceiling is enforced strictly before dispatch, and the wall-clock ceiling
    additionally caps each in-flight request at its remaining budget, so one
    hanging transport (default timeout 60s) cannot run far past the clock. A
    *measured* ceiling whose evidence is absent (no provider usage, no
    pricing) can never fire, so charging halts the campaign instead —
    absent evidence fails closed, it never lets a pool run unbounded.
    """

    def __init__(
        self,
        ceilings: CampaignCeilings,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        ensure_bounded(ceilings)  # an unbounded policy never becomes enforcement
        self.ceilings = ceilings
        self._clock = clock
        self._started = clock()
        self.spend_usd = 0.0
        self.input_tokens = 0
        self.output_tokens = 0
        self.model_calls = 0
        self.objectives_attempted = 0
        #: A stop observed by the dispatch seam (between the attempt-level
        #: check and dispatch) is authoritative for the report even though
        #: the post-dispatch counters it fired on may read just under.
        self.cached_stop: StopReason | None = None

    def halt(self, stop: StopReason) -> None:
        """Record a stop observed inside the dispatch seam."""
        self.cached_stop = stop

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def elapsed_s(self) -> float:
        return self._clock() - self._started

    def remaining_wall_clock_s(self) -> float | None:
        """Seconds left under the wall-clock ceiling; ``None`` when unbounded."""
        if self.ceilings.max_wall_clock_s is None:
            return None
        return self.ceilings.max_wall_clock_s - self.elapsed_s

    def charge(self, usage: InvocationUsage | None) -> None:
        """Charge one terminalized Invocation's measured usage.

        ``None`` usage (the provider reported nothing, #718) still counts
        toward the call ceiling — taken at admission in :meth:`admit_call`,
        so failed dispatches consume it too — but charges no tokens and no
        spend: an unmeasured call is absent evidence, never a free one.
        Absent evidence is also fail-closed: if a ceiling is measured from
        the very counter that cannot advance, :meth:`halt` fires
        immediately, so the walk stops rather than dispatching the rest of
        the pool against a ceiling that can never be reached.
        """
        if usage is None:
            self._halt_on_absent_evidence(tokens_reported=False)
            return
        self.input_tokens += usage.input_units
        self.output_tokens += usage.output_units
        if usage.cost_cents is not None:
            self.spend_usd += usage.cost_cents / 100.0
        else:
            self._halt_on_absent_evidence(tokens_reported=True)

    def _halt_on_absent_evidence(self, *, tokens_reported: bool) -> None:
        """Halt when a declared ceiling's evidence cannot ever arrive."""
        c = self.ceilings
        if not tokens_reported and c.max_total_tokens is not None:
            self.halt(
                StopReason(
                    ceiling="max_total_tokens",
                    observed=float(self.total_tokens),
                    limit=float(c.max_total_tokens),
                    evidence_missing=True,
                )
            )
        elif c.max_spend_usd is not None:
            self.halt(
                StopReason(
                    ceiling="max_spend_usd",
                    observed=self.spend_usd,
                    limit=float(c.max_spend_usd),
                    evidence_missing=True,
                )
            )

    def stop_reason(self) -> StopReason | None:
        c = self.ceilings
        limits: list[tuple[str, float, float | None]] = [
            ("max_spend_usd", self.spend_usd, c.max_spend_usd),
            (
                "max_total_tokens",
                float(self.total_tokens),
                None if c.max_total_tokens is None else float(c.max_total_tokens),
            ),
            (
                "max_model_calls",
                float(self.model_calls),
                None if c.max_model_calls is None else float(c.max_model_calls),
            ),
            ("max_wall_clock_s", self.elapsed_s, c.max_wall_clock_s),
            (
                "max_objectives",
                float(self.objectives_attempted),
                None if c.max_objectives is None else float(c.max_objectives),
            ),
        ]
        for ceiling, observed, limit in limits:
            if limit is not None and observed >= limit:
                return StopReason(ceiling=ceiling, observed=observed, limit=limit)
        return None

    def wall_clock_stop(self) -> StopReason | None:
        """The wall-clock stop once the ceiling has already expired.

        Lives beside the ceilings it enforces so the expiry test and the
        stop it reports read the same limit; the dispatch seam raises the
        returned stop when an in-flight request is cancelled at the
        remaining budget, instead of re-deriving the comparison (and its
        ``None`` handling) at the raise site.
        """
        limit = self.ceilings.max_wall_clock_s
        if limit is not None and self.elapsed_s >= limit:
            return StopReason(ceiling="max_wall_clock_s", observed=self.elapsed_s, limit=limit)
        return None

    def admit_call(self) -> None:
        """Mechanical pre-dispatch gate inside the invocation seam."""
        stop = self.cached_stop or self.stop_reason()
        if stop is not None:
            raise BudgetExhausted(stop)
        # The dispatch count advances at admission, not on success: a call
        # that raises (timeout, 5xx) may still have been received and served
        # by the provider, so every admitted dispatch consumes one unit of
        # the max_model_calls ceiling. Success-path charge() adds only the
        # measured usage.
        self.model_calls += 1


# -- recorded dispatch -------------------------------------------------------


async def _terminalize_unknown(
    store: InMemoryInvocationStore, invocation: Invocation, error: str
) -> None:
    """Terminalize an ambiguous dispatch as ``UNKNOWN``.

    A cancellation, timeout, connection loss, or arbitrary provider error
    does not prove the external effect was unapplied, so the row is never
    the safe-to-retry ``FAILED`` — canonical terminalization reserves that
    status for ``EffectNotApplied`` (``CapabilityEffectContext
    ._run_provider``). The store assigns the new revision on save (OCC);
    sending a pre-incremented one would be stale.
    """
    await store.save(
        invocation.model_copy(
            update={
                "status": InvocationStatus.UNKNOWN,
                "error": error,
                "finished_at": _utc_now(),
            }
        )
    )


async def _recorded_call(
    *,
    call: ModelCall,
    store: InMemoryInvocationStore,
    recorder: CanonicalInvocationUsageRecorder,
    budget: BudgetState,
    binding: ResolvedBinding,
    run_id: str,
    node_run_id: str,
    attempt_id: str,
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int,
    pricing: ModelMetadata | None,
) -> ModelCallResult:
    """Dispatch one model call as a canonical Invocation.

    The Invocation is admitted into the store before dispatch, terminalized
    from the outcome, and charged to the quota ledger exactly once through
    the canonical recorder — retries cannot double-charge, and no campaign
    model call can bypass the seam because this *is* the dispatch path.
    """
    budget.admit_call()
    invocation = Invocation(
        run_id=run_id,
        node_run_id=node_run_id,
        attempt_id=attempt_id,
        workspace_id=binding.workspace_id,
        project_id=binding.project_id,
        binding=binding,
        effect_key=f"{MODEL_CHAT_CAPABILITY}:{node_run_id}",
        status=InvocationStatus.RUNNING,
        started_at=_utc_now(),
        request={"message_count": len(messages), "max_tokens": max_tokens},
    )
    await store.create(invocation)
    try:
        # The wall-clock ceiling bounds the in-flight request too, not just
        # the pre-dispatch gate: the request is cancelled once its remaining
        # budget expires, so a hanging transport (default timeout 60s) cannot
        # run the clock far past ``max_wall_clock_s``. ``wait_for(None)``
        # awaits directly, so an unbounded clock adds no wrapping.
        result = await asyncio.wait_for(
            call(messages, temperature=temperature, max_tokens=max_tokens),
            timeout=budget.remaining_wall_clock_s(),
        )
    except EffectNotApplied as exc:
        # Canonical terminalization semantics (CapabilityEffectContext
        # ._run_provider): FAILED is reserved for provably-unapplied effects.
        failed = invocation.model_copy(
            update={
                "status": InvocationStatus.FAILED,
                "error": str(exc),
                "finished_at": _utc_now(),
            }
        )
        await store.save(failed)
        raise
    except asyncio.CancelledError:
        # Cancellation leaves the external outcome ambiguous; mark UNKNOWN so
        # the row is terminal and never reads as safe-to-retry FAILED.
        await _terminalize_unknown(
            store,
            invocation,
            "provider invocation cancelled with unknown external outcome",
        )
        raise
    except TimeoutError as exc:
        # The wall-clock ceiling expired mid-flight: the request was cancelled
        # at its remaining budget, leaving the external outcome ambiguous, so
        # the row terminalizes as UNKNOWN (never safe-to-retry FAILED) and the
        # expiry surfaces as the designed mechanical stop — the campaign stops
        # on the clock rather than recording an intervention. A transport
        # timeout of its own raises its own error type; if one surfaces as a
        # builtin TimeoutError while budget remains, it re-raises unchanged.
        await _terminalize_unknown(store, invocation, str(exc) or type(exc).__name__)
        stop = budget.wall_clock_stop()
        if stop is not None:
            raise BudgetExhausted(stop) from exc
        raise
    except Exception as exc:
        # Audit evidence only: a timeout, connection loss, or provider error
        # does not prove the effect was unapplied, so it terminalizes as
        # UNKNOWN (never FAILED), keeping ambiguous calls out of the
        # safe-to-retry set. No tokens or spend are charged; the call ceiling
        # was already consumed at admission (admit_call). A refused or failed
        # dispatch has no measured usage, and charging an unreported-request
        # marker would fabricate token/spend evidence (the #717/#718
        # anti-pattern).
        await _terminalize_unknown(store, invocation, str(exc) or type(exc).__name__)
        raise
    # Absent provider usage stays None on the Invocation: the canonical
    # recorder keys "reported" off usage-is-not-None, so a zero-filled row
    # would read as reported zeros — the exact #717/#718 anti-pattern.
    usage: InvocationUsage | None = None
    if result.usage_reported:
        usage = InvocationUsage(
            input_units=result.input_tokens,
            output_units=result.output_tokens,
            cost_cents=(
                compute_cost_cents(pricing, result.input_tokens, result.output_tokens)
                if pricing is not None
                else None
            ),
            model=binding.provider_name,
            model_version=result.model_version,
            provider=binding.provider_name,
        )
    completed = invocation.model_copy(
        update={
            "status": InvocationStatus.COMPLETED,
            "result": {"content_chars": len(result.content)},
            "usage": usage,
            "finished_at": _utc_now(),
        }
    )
    await store.save(completed)
    await recorder.record(completed)
    budget.charge(usage)
    return result


def _utc_now() -> datetime:
    return datetime.now(UTC)


# -- campaign arms and reporting --------------------------------------------


class ArmPolicy(BaseModel):
    """One campaign arm: which model answers, at what sampling settings."""

    model_config = ConfigDict(extra="forbid")

    arm_id: NonEmptyStr
    model: NonEmptyStr
    temperature: float = 0.2
    max_tokens: int = 2048


class AttemptRecord(BaseModel):
    """One dispatched attempt, with its outcome and measured cost."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    arm_id: str
    objective_id: str
    attempt: int
    score: float | None = None
    verified_progress: bool = False
    intervention: bool = False
    intervention_reason: str | None = None
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    #: Evidence flags for the zero-filled counters above (#717/#718): the
    #: serialized report must distinguish a measured zero-token/free call
    #: from a call whose usage or pricing evidence never arrived.
    usage_reported: bool = False
    cost_known: bool = False


class ArmResult(BaseModel):
    """One arm's observed campaign outcomes."""

    model_config = ConfigDict(extra="forbid")

    arm_id: str
    model: str
    objectives_attempted: int = 0
    attempts: int = 0
    verified_progress: int = 0
    regressions: int = 0
    interventions: int = 0
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    #: Absent-evidence accounting (#718): how many dispatched attempts
    #: entered the report with zero-filled counters because the provider
    #: sent no usage (or no pricing metadata was available), so the
    #: aggregate zeros are not silently read as measured zeros.
    attempts_without_usage_report: int = 0
    attempts_with_unknown_cost: int = 0
    scores: dict[str, float] = Field(default_factory=dict)
    stop_reason: StopReason | None = None
    attempts_log: tuple[AttemptRecord, ...] = ()
    #: interventions / attempts; 0.0 with no attempts (no work, no
    #: interventions demanded). Serialized so the report artifact carries the
    #: rate explicitly, not just its numerator and denominator.
    intervention_rate: float = 0.0


class ArmComparison(BaseModel):
    """Frontier-vs-baseline outcome on the shared objective pool."""

    model_config = ConfigDict(extra="forbid")

    frontier_arm: str
    baseline_arm: str
    objectives_compared: int
    frontier_wins: int
    baseline_wins: int
    ties: int
    mean_score_delta: float
    frontier_cost_usd: float
    baseline_cost_usd: float
    cost_multiple: float | None = None


class CampaignReport(BaseModel):
    """The campaign's verified record: progress, cost, attempts, regressions,
    intervention rates, and the mechanical stop that ended each arm."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    ceilings: CampaignCeilings
    arms: tuple[ArmResult, ...]
    comparison: ArmComparison | None = None
    #: Refused (arm, objective) admission events: pool entries whose declared
    #: paths fall outside the campaign's work-scope ceiling. Counted per arm,
    #: so a two-arm campaign counts an out-of-scope objective twice.
    scope_refusals: int = 0
    started_at: float
    finished_at: float

    def to_json(self, *, indent: int = 2) -> str:
        return self.model_dump_json(indent=indent)


# -- runner ------------------------------------------------------------------


ScoreFn = Callable[[Objective, str], float]


class _ArmLedger:
    """Mutable per-arm accumulator folded into an ``ArmResult`` at the end."""

    def __init__(self, arm: ArmPolicy) -> None:
        self.arm = arm
        self.objectives_attempted = 0
        self.verified_progress = 0
        self.interventions = 0
        self.cost_usd = 0.0
        self.input_tokens = 0
        self.output_tokens = 0
        self.attempts_without_usage_report = 0
        self.attempts_with_unknown_cost = 0
        self.scores: dict[str, float] = {}
        self.log: list[AttemptRecord] = []


def _normalized_repo_path(path: str) -> str | None:
    """Normalized repo-relative form of *path*, or ``None`` when it escapes
    the repo (absolute paths, empty paths, or ``..`` traversal climbing out)."""
    if not path:
        return None
    normalized = posixpath.normpath(path)
    if normalized == "." or normalized.startswith(("/", "../")) or normalized == "..":
        return None
    return normalized


def _under_prefix(path: str, prefix: str) -> bool:
    """Component-wise containment of *path* under the *prefix* directory."""
    if prefix == "":
        return True  # empty prefix historically admits the whole repo
    norm_prefix = posixpath.normpath(prefix)
    if norm_prefix in (".", "/"):
        return True
    return path == norm_prefix or path.startswith(norm_prefix + "/")


def _in_scope(paths: tuple[str, ...], allowed: tuple[str, ...]) -> bool:
    """Work-scope admission: every declared path normalizes to a repo-relative
    location under an allowed prefix. Traversal is rejected and containment is
    checked by path components rather than raw string prefixes, so a path such
    as ``src/../secrets.txt`` cannot pass a ``src/`` ceiling."""
    normalized: list[str] = []
    for path in paths:
        rel = _normalized_repo_path(path)
        if rel is None:
            return False
        normalized.append(rel)
    return all(any(_under_prefix(rel, prefix) for prefix in allowed) for rel in normalized)


@dataclass
class _ArmContext:
    """Everything one arm's walk over the pool needs."""

    run_id: str
    arm: ArmPolicy
    budget: BudgetState
    ledger: _ArmLedger
    ceilings: CampaignCeilings
    call: ModelCall
    metadata: ModelMetadata | None
    binding: ResolvedBinding
    store: InMemoryInvocationStore
    recorder: CanonicalInvocationUsageRecorder
    scorer: ScoreFn
    progress_threshold: float
    attempt_ordinal: dict[str, int]
    scope_refusals: int = 0


async def _stop_logged(ctx: _ArmContext, stop: StopReason) -> None:
    """Record a mechanical ceiling stop in the campaign log."""
    await logger.ainfo(
        "rsi_campaign_ceiling_reached",
        run_id=ctx.run_id,
        arm=ctx.arm.arm_id,
        ceiling=stop.ceiling,
        observed=stop.observed,
        limit=stop.limit,
    )


async def _refuse_out_of_scope(ctx: _ArmContext, objective: Objective) -> None:
    """Record a work-scope refusal: refused work consumes no model budget."""
    ctx.scope_refusals += 1
    await logger.awarning(
        "rsi_campaign_scope_refused",
        run_id=ctx.run_id,
        arm=ctx.arm.arm_id,
        objective=objective.objective_id,
        paths=objective.paths,
        allowed=ctx.ceilings.allowed_paths,
    )


async def _dispatch_attempt(
    ctx: _ArmContext, objective: Objective, ordinal: int
) -> tuple[str, Any]:
    """Dispatch one recorded attempt.

    Returns ``(kind, payload)``: ``("ok", ModelCallResult)``,
    ``("stop", StopReason)`` when the dispatch seam's budget gate refused,
    or ``("failed", reason)`` for a hard failure the loop cannot resolve
    autonomously — an intervention by definition.
    """
    arm = ctx.arm
    try:
        result = await _recorded_call(
            call=ctx.call,
            store=ctx.store,
            recorder=ctx.recorder,
            budget=ctx.budget,
            binding=ctx.binding,
            run_id=ctx.run_id,
            node_run_id=f"{arm.arm_id}:{objective.objective_id}",
            attempt_id=f"attempt-{ctx.run_id}-{arm.arm_id}-{objective.objective_id}-{ordinal}",
            messages=[{"role": "user", "content": objective.task}],
            temperature=arm.temperature,
            max_tokens=arm.max_tokens,
            pricing=ctx.metadata,
        )
    except BudgetExhausted as exc:
        # The dispatch seam refused: a ceiling fired between the attempt-level
        # check and dispatch. This is the campaign's designed mechanical stop,
        # not an intervention — nothing was dispatched and no budget was
        # consumed.
        return ("stop", exc.stop)
    except Exception as exc:
        return ("failed", str(exc))
    return ("ok", result)


def _measure_cost(ctx: _ArmContext, result: ModelCallResult) -> float:
    """Operator-declared pricing -> dollars; absent pricing stays zero."""
    if ctx.metadata is None or not result.usage_reported:
        return 0.0
    return compute_cost_cents(ctx.metadata, result.input_tokens, result.output_tokens) / 100.0


async def _score_attempt(
    ctx: _ArmContext, objective: Objective, ordinal: int, result: ModelCallResult
) -> None:
    """Score a completed attempt, fold it into the arm ledger and log it."""
    arm, ledger = ctx.arm, ctx.ledger
    score = ctx.scorer(objective, result.content)
    verified = score >= ctx.progress_threshold
    cost = _measure_cost(ctx, result)
    reported = result.input_tokens if result.usage_reported else 0
    usage_reported = result.usage_reported
    cost_known = usage_reported and ctx.metadata is not None
    if not usage_reported:
        ledger.attempts_without_usage_report += 1
    if not cost_known:
        ledger.attempts_with_unknown_cost += 1
    ledger.scores[objective.objective_id] = max(
        score, ledger.scores.get(objective.objective_id, score)
    )
    if verified:
        ledger.verified_progress += 1
    ledger.cost_usd += cost
    ledger.input_tokens += reported
    ledger.output_tokens += result.output_tokens if result.usage_reported else 0
    ledger.log.append(
        AttemptRecord(
            arm_id=arm.arm_id,
            objective_id=objective.objective_id,
            attempt=ordinal,
            score=score,
            verified_progress=verified,
            cost_usd=cost,
            input_tokens=reported,
            output_tokens=result.output_tokens if result.usage_reported else 0,
            usage_reported=usage_reported,
            cost_known=cost_known,
        )
    )


async def _walk_pool(ctx: _ArmContext, pool: ObjectivePool) -> None:
    """Walk one arm over the shared pool under the ceilings.

    Refused work (scope) consumes no budget; a reached ceiling stops the walk
    between attempts, and the dispatch seam refuses again inside the attempt
    so no ceiling can be crossed unnoticed.
    """
    arm, budget, ledger = ctx.arm, ctx.budget, ctx.ledger
    for objective in pool.objectives:
        # Mechanical stop: no new work once a ceiling is reached (Q3), and
        # none either when a measured ceiling's evidence went absent mid-walk
        # (charge() halts; the very next iteration refuses here).
        stop = budget.cached_stop or budget.stop_reason()
        if stop is not None:
            await _stop_logged(ctx, stop)
            return
        if ctx.ceilings.allowed_paths and not _in_scope(
            objective.paths, ctx.ceilings.allowed_paths
        ):
            await _refuse_out_of_scope(ctx, objective)
            continue

        budget.objectives_attempted += 1
        ledger.objectives_attempted += 1
        ctx.attempt_ordinal[arm.arm_id] += 1
        ordinal = ctx.attempt_ordinal[arm.arm_id]
        kind, payload = await _dispatch_attempt(ctx, objective, ordinal)
        if kind == "stop":
            budget.halt(payload)
            return
        if kind == "failed":
            ledger.log.append(
                AttemptRecord(
                    arm_id=arm.arm_id,
                    objective_id=objective.objective_id,
                    attempt=ordinal,
                    intervention=True,
                    intervention_reason=payload,
                )
            )
            ledger.interventions += 1
            continue
        await _score_attempt(ctx, objective, ordinal, payload)


def _arm_context(
    *,
    run_id: str,
    arm: ArmPolicy,
    ceilings: CampaignCeilings,
    budget: BudgetState,
    ledger: _ArmLedger,
    make_model_call: Callable[[ArmPolicy], ModelCall],
    pricing: Callable[[ArmPolicy], ModelMetadata | None] | None,
    store: InMemoryInvocationStore,
    recorder: CanonicalInvocationUsageRecorder,
    scorer: ScoreFn,
    progress_threshold: float,
    attempt_ordinal: dict[str, int],
    workspace_id: str,
    project_id: str,
) -> _ArmContext:
    """Assemble one arm's execution context: transport, pricing, binding."""
    return _ArmContext(
        run_id=run_id,
        arm=arm,
        budget=budget,
        ledger=ledger,
        ceilings=ceilings,
        call=make_model_call(arm),
        metadata=pricing(arm) if pricing is not None else None,
        binding=ResolvedBinding(
            binding_id=f"binding-{run_id}-{arm.arm_id}",
            workspace_id=workspace_id,
            project_id=project_id,
            capability=MODEL_CHAT_CAPABILITY,
            provider_name=arm.model,
            provider_trust_tier="gateway-aliased",
        ),
        store=store,
        recorder=recorder,
        scorer=scorer,
        progress_threshold=progress_threshold,
        attempt_ordinal=attempt_ordinal,
    )


def _arm_result(
    arm: ArmPolicy, ledger: _ArmLedger, budget: BudgetState, attempts: int
) -> ArmResult:
    """Fold one arm's mutable ledger into its reported outcome."""
    return ArmResult(
        arm_id=arm.arm_id,
        model=arm.model,
        objectives_attempted=ledger.objectives_attempted,
        attempts=attempts,
        verified_progress=ledger.verified_progress,
        interventions=ledger.interventions,
        cost_usd=ledger.cost_usd,
        input_tokens=ledger.input_tokens,
        output_tokens=ledger.output_tokens,
        attempts_without_usage_report=ledger.attempts_without_usage_report,
        attempts_with_unknown_cost=ledger.attempts_with_unknown_cost,
        scores=dict(sorted(ledger.scores.items())),
        stop_reason=budget.cached_stop or budget.stop_reason(),
        attempts_log=tuple(ledger.log),
        intervention_rate=ledger.interventions / attempts if attempts else 0.0,
    )


async def run_campaign(
    *,
    run_id: str,
    pool: ObjectivePool,
    arms: Sequence[ArmPolicy],
    ceilings: CampaignCeilings,
    make_model_call: Callable[[ArmPolicy], ModelCall],
    store: InMemoryInvocationStore | None = None,
    usage_log: InMemoryUsageLog | None = None,
    quota_tracker: Any | None = None,
    pricing: Callable[[ArmPolicy], ModelMetadata | None] | None = None,
    scorer: ScoreFn = keyword_objective_scorer,
    progress_threshold: float = 1.0,
    regression_tolerance: float = 0.0,
    clock: Callable[[], float] = time.monotonic,
    workspace_id: str = "",
    project_id: str = "",
) -> CampaignReport:
    """Run every arm over the shared objective pool under the ceilings.

    The pool is shared verbatim between arms — the comparison never
    confounds objective sets. Each arm stops mechanically at the first
    ceiling it reaches (checked before every attempt and inside the dispatch
    seam); arms are independent, so one arm exhausting the budget does not
    silently consume the other's record. Every dispatched call is a
    canonical Invocation charged once to the quota ledger.

    ``regression_tolerance`` sizes the cross-arm regression band: an arm
    regressed on an objective when it scored below every peer arm's score on
    the same shared objective by more than the tolerance.
    """
    if not arms:
        raise ValueError("a campaign needs at least one arm")
    ensure_unique_objectives(pool)
    ensure_unique_arm_ids(arms)
    if workspace_id.strip() == "" or project_id.strip() == "":
        raise ValueError("a campaign Invocation must carry workspace and project scope")
    started = clock()
    store = store or InMemoryInvocationStore()
    usage_log = usage_log or InMemoryUsageLog()
    recorder = CanonicalInvocationUsageRecorder(usage_log, quota_tracker)

    arm_results, scope_refusals = await _drive_arms(
        run_id=run_id,
        pool=pool,
        arms=arms,
        ceilings=ceilings,
        make_model_call=make_model_call,
        pricing=pricing,
        scorer=scorer,
        progress_threshold=progress_threshold,
        store=store,
        recorder=recorder,
        clock=clock,
        workspace_id=workspace_id,
        project_id=project_id,
    )

    return CampaignReport(
        run_id=run_id,
        ceilings=ceilings,
        arms=_with_cross_arm_regressions(arm_results, tolerance=regression_tolerance),
        comparison=_compare(arm_results),
        scope_refusals=scope_refusals,
        started_at=started,
        finished_at=clock(),
    )


async def _drive_arms(
    *,
    run_id: str,
    pool: ObjectivePool,
    arms: Sequence[ArmPolicy],
    ceilings: CampaignCeilings,
    make_model_call: Callable[[ArmPolicy], ModelCall],
    pricing: Callable[[ArmPolicy], ModelMetadata | None] | None,
    scorer: ScoreFn,
    progress_threshold: float,
    store: InMemoryInvocationStore,
    recorder: CanonicalInvocationUsageRecorder,
    clock: Callable[[], float],
    workspace_id: str,
    project_id: str,
) -> tuple[tuple[ArmResult, ...], int]:
    """Walk every arm over the pool; return outcomes and scope refusals."""
    ledgers = {arm.arm_id: _ArmLedger(arm) for arm in arms}
    budgets = {arm.arm_id: BudgetState(ceilings, clock=clock) for arm in arms}
    attempt_ordinal = {arm.arm_id: 0 for arm in arms}
    scope_refusals = 0

    for arm in arms:
        ctx = _arm_context(
            run_id=run_id,
            arm=arm,
            ceilings=ceilings,
            budget=budgets[arm.arm_id],
            ledger=ledgers[arm.arm_id],
            make_model_call=make_model_call,
            pricing=pricing,
            store=store,
            recorder=recorder,
            scorer=scorer,
            progress_threshold=progress_threshold,
            attempt_ordinal=attempt_ordinal,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        await _walk_pool(ctx, pool)
        scope_refusals += ctx.scope_refusals

    arm_results = tuple(
        _arm_result(arm, ledgers[arm.arm_id], budgets[arm.arm_id], attempt_ordinal[arm.arm_id])
        for arm in arms
    )
    return arm_results, scope_refusals


def _with_cross_arm_regressions(
    results: tuple[ArmResult, ...], *, tolerance: float
) -> tuple[ArmResult, ...]:
    """Count, per arm, the shared objectives it scored below every peer on.

    Both arms walked the same pool, so a per-objective comparison is always
    defined where both arms produced a score. An objective only one arm
    reached regresses nothing: there is no peer score to fall below.
    """

    def regressions_for(result: ArmResult) -> int:
        peers = [other for other in results if other.arm_id != result.arm_id]
        count = 0
        for objective_id, score in result.scores.items():
            peer_scores = [
                other.scores[objective_id] for other in peers if objective_id in other.scores
            ]
            if peer_scores and score < min(peer_scores) - tolerance:
                count += 1
        return count

    return tuple(
        result.model_copy(update={"regressions": regressions_for(result)}) for result in results
    )


def _compare(results: tuple[ArmResult, ...]) -> ArmComparison | None:
    """Compare the first two arms (frontier first) on the shared pool.

    Both arms walked the identical pool, so a comparison is only defined
    when both produced a score for every pool objective. Divergent score
    coverage means one arm stopped early on a ceiling; refuse rather than
    silently compare the shared prefix (partial coverage must not read as
    a valid frontier-versus-baseline result).
    """
    if len(results) < 2:
        return None
    frontier, baseline = results[0], results[1]
    if set(frontier.scores) != set(baseline.scores):
        return None
    shared = sorted(frontier.scores)
    wins = sum(1 for oid in shared if frontier.scores[oid] > baseline.scores[oid])
    losses = sum(1 for oid in shared if frontier.scores[oid] < baseline.scores[oid])
    ties = len(shared) - wins - losses
    delta = (
        sum(frontier.scores[oid] - baseline.scores[oid] for oid in shared) / len(shared)
        if shared
        else 0.0
    )
    cost_multiple = frontier.cost_usd / baseline.cost_usd if baseline.cost_usd > 0.0 else None
    return ArmComparison(
        frontier_arm=frontier.arm_id,
        baseline_arm=baseline.arm_id,
        objectives_compared=len(shared),
        frontier_wins=wins,
        baseline_wins=losses,
        ties=ties,
        mean_score_delta=delta,
        frontier_cost_usd=frontier.cost_usd,
        baseline_cost_usd=baseline.cost_usd,
        cost_multiple=cost_multiple,
    )
