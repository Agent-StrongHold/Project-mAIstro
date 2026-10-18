"""Explore-wave provenance on the canonical Run spine (M7-A8).

A design Run can emit an **explore wave**: N divergent theses, each persisted
as a NodeRun on the *same* Run, each carrying its thesis text, wave index and
the Goal + Rubric revisions it was emitted under. This module is the contract
for that fan-out. It is deliberately small:

- The wave is not a new Run identity. Wave N+1 is a later fan-out of NodeRuns
  under the same ``run_id``, after the fence (#794) produces its redirect.
- The thesis is not prompt text and not a client-side candidate list. It is a
  durable record on the child NodeRun's ``provenance`` (#M7-A8 contract:
  "stored on the child NodeRun / artifact provenance").
- Repeating a rejected thesis is a contract failure
  (:class:`DuplicateThesisError`), so a later wave cannot silently repeat what
  an earlier wave already rejected.
- Scoring is eval-on-Run (#792) shape: every thesis of a wave is scored
  against the *same* Rubric revision the wave was emitted under; naming a
  winner marks the others as losers and they remain queryable.
- ``ExplorationPolicy`` is a pack-declared, per-Run-overridable parameter. The
  three policies are values of one enum — not three products.

This module does **not** import or revive ``maistro.orchestrator.waves``
(ADR-052 / SPEC-255). That island is unreachable dead code pending the C6
reachability decision and is never the owner of design exploration; the
canonical ``Goal -> Graph -> Run -> NodeRun -> Attempt`` spine is.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from maistro.runs.model import NodeRun, Run
from maistro.runs.store import (
    NodeRunNotFound,
    RunIntegrityError,
    RunNotFound,
)

#: ``NodeRun.provenance`` key holding the :class:`ThesisProvenance` record.
PROVENANCE_KEY = "explore_wave"

#: ``Run.provenance`` key holding the run's :class:`ExplorationPlan` — the
#: pack-declared (per-Run overridable) policy and width, visible on the Run.
RUN_PROVENANCE_KEY = "exploration"


class ExplorationPolicy(StrEnum):
    """Pack-declared exploration policy, overridable per Run.

    One enum, not three products: the policy shapes how a pack's explore Graph
    template diverges and converges, and is visible on the Run for every
    policy. ``wide-then-converge`` — wave 1 divergent, later waves condition on
    rejected theses plus the director redirect. ``tight`` — small width, honor
    constraints, little divergence. ``tournament`` — same-wave theses scored
    comparatively under the Rubric; a winner is named, losers remain
    queryable. Tournament scoring stays eval-on-Run (#792); it never summons
    Evolve as an in-Run critic (#796).
    """

    WIDE_THEN_CONVERGE = "wide-then-converge"
    TIGHT = "tight"
    TOURNAMENT = "tournament"


class ThesisDisposition(StrEnum):
    """Where one thesis stands in the wave's eval/fence lifecycle."""

    PROPOSED = "proposed"
    SCORED = "scored"
    WINNER = "winner"
    LOSER = "loser"
    PARKED = "parked"
    REDIRECTED = "redirected"


#: Dispositions that make a thesis part of the rejected-thesis list a later
#: wave must not repeat. The wave winner is accepted, not rejected.
REJECTED_DISPOSITIONS = frozenset(
    {
        ThesisDisposition.LOSER,
        ThesisDisposition.PARKED,
        ThesisDisposition.REDIRECTED,
    }
)


class ExplorationContractError(RunIntegrityError):
    """Base class for explore-wave contract failures."""


class ThesisWidthMismatchError(ExplorationContractError):
    """A wave was asked to fan out a thesis count other than its width."""


class DuplicateThesisError(ExplorationContractError):
    """A wave tried to persist a thesis that an earlier wave already rejected."""


class RubricRevisionMismatchError(ExplorationContractError):
    """A thesis was scored against a Rubric revision other than its own."""


class WaveWinnerAlreadyNamedError(ExplorationContractError):
    """A wave whose winner is already named was handed a different winner."""


class ThesisNotInWaveError(ExplorationContractError):
    """A winner or score was addressed to a NodeRun outside the target wave."""


class ThesisSettledError(ExplorationContractError):
    """A settled thesis (winner/loser/parked/redirected) was mutated again."""


class ExplorationPlan(BaseModel):
    """The pack-declared exploration parameters a design Run runs under.

    Declared by the pack's Graph template (default width comes from the pack),
    overridable per Run: a human may tighten ``width`` without changing Goal
    identity — ``goal_revision`` is recorded, not derived from width.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    policy: ExplorationPolicy
    width: int = Field(ge=1)
    goal_revision: str = Field(min_length=1)
    rubric_revision: str = Field(min_length=1)

    @field_validator("goal_revision", "rubric_revision")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("revision identifiers must be non-empty")
        return value

    def run_provenance(self) -> dict[str, Any]:
        """The ``Run.provenance`` entry that makes the plan visible on the Run."""
        return {RUN_PROVENANCE_KEY: self.model_dump(mode="json")}


class ThesisProvenance(BaseModel):
    """The named bet of one candidate, durable on its child NodeRun.

    Written once by :func:`fan_out_wave` and frozen: thesis text, wave index
    and the Goal/Rubric revisions are identity, never rewritten by later waves
    or by scoring.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    thesis_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    thesis: str = Field(min_length=1)
    wave_index: int = Field(ge=1)
    slot: int = Field(ge=0)
    policy: ExplorationPolicy
    width: int = Field(ge=1)
    parent_node_id: str = Field(min_length=1)
    goal_revision: str = Field(min_length=1)
    rubric_revision: str = Field(min_length=1)

    @field_validator("thesis", "parent_node_id", "goal_revision", "rubric_revision")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("thesis identity fields must be non-empty")
        return value


class ThesisScore(BaseModel):
    """One eval-on-Run (#792) score of a thesis against the wave's Rubric."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rubric_revision: str = Field(min_length=1)
    score: float
    rationale: str = ""


class ThesisRecord(BaseModel):
    """Queryable projection of one thesis NodeRun of a wave."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    node_run_id: str
    thesis: ThesisProvenance
    disposition: ThesisDisposition = ThesisDisposition.PROPOSED
    score: ThesisScore | None = None


class ExplorationRunStore(Protocol):
    """The slice of ``RunStore`` the wave contract needs."""

    async def get_run(self, run_id: str) -> Run | None: ...

    async def get_node_run(self, node_run_id: str) -> NodeRun | None: ...

    async def list_node_runs(self, run_id: str) -> list[NodeRun]: ...

    async def create_node_run(
        self, run_id: str, *, node_id: str, provenance: dict[str, Any] | None = None
    ) -> NodeRun: ...

    async def record_node_run_provenance(
        self, node_run_id: str, *, patch: dict[str, Any]
    ) -> NodeRun: ...


def _normalize_thesis(text: str) -> str:
    """Collapse a thesis text to its comparison form.

    Divergence is about content, not formatting: whitespace runs and case are
    not the difference between two bets.
    """
    return " ".join(text.split()).casefold()


def exploration_plan_of(run: Run) -> ExplorationPlan | None:
    """Read the exploration plan visible on a Run's provenance, if any."""
    recorded = run.provenance.get(RUN_PROVENANCE_KEY)
    if recorded is None:
        return None
    return ExplorationPlan.model_validate(recorded)


def _wave_record_of(node_run: NodeRun) -> dict[str, Any]:
    """The full ``PROVENANCE_KEY`` record of a thesis NodeRun.

    Shape: ``{"thesis": <identity>, "disposition": <state>, "score": <eval>}``
    — the nested ``thesis`` is written once at fan-out and never rewritten;
    ``disposition`` and ``score`` progress through the eval/fence lifecycle.
    """
    recorded = node_run.provenance.get(PROVENANCE_KEY)
    if recorded is None:
        raise ThesisNotInWaveError(
            f"NodeRun {node_run.node_run_id!r} carries no {PROVENANCE_KEY!r} record"
        )
    if not isinstance(recorded, dict) or not isinstance(recorded.get("thesis"), dict):
        raise ExplorationContractError(
            f"NodeRun {node_run.node_run_id!r} carries a malformed {PROVENANCE_KEY!r} record"
        )
    return recorded


def thesis_provenance_of(node_run: NodeRun) -> ThesisProvenance | None:
    """Read the thesis identity durable on a NodeRun, if it carries one."""
    recorded = node_run.provenance.get(PROVENANCE_KEY)
    if recorded is None:
        return None
    return ThesisProvenance.model_validate(_wave_record_of(node_run)["thesis"])


def _thesis_record_of(node_run: NodeRun) -> ThesisRecord:
    recorded = _wave_record_of(node_run)
    disposition = ThesisDisposition(recorded.get("disposition", ThesisDisposition.PROPOSED.value))
    score = recorded.get("score")
    return ThesisRecord(
        node_run_id=node_run.node_run_id,
        thesis=ThesisProvenance.model_validate(recorded["thesis"]),
        disposition=disposition,
        score=ThesisScore.model_validate(score) if score is not None else None,
    )


def wave_records(node_runs: Sequence[NodeRun], wave_index: int | None = None) -> list[ThesisRecord]:
    """Every thesis of a wave — winners and losers alike — queryable off a Run.

    Losers never disappear when a winner is named: they stay right here, which
    is what makes them consumable input for the next wave and auditable
    history afterwards.
    """
    records = [
        _thesis_record_of(node_run)
        for node_run in sorted(node_runs, key=lambda nr: nr.ordinal)
        if node_run.provenance.get(PROVENANCE_KEY) is not None
    ]
    if wave_index is not None:
        records = [record for record in records if record.thesis.wave_index == wave_index]
    return records


def rejected_thesis_texts(node_runs: Sequence[NodeRun]) -> tuple[str, ...]:
    """The rejected-thesis list a later wave is given as its forbidden set."""
    return tuple(
        record.thesis.thesis
        for record in wave_records(node_runs)
        if record.disposition in REJECTED_DISPOSITIONS
    )


def _validate_wave_fanout(
    run: Run,
    *,
    plan: ExplorationPlan,
    wave_index: int,
    parent_node_id: str,
    theses: Sequence[str],
    rejected_theses: Sequence[str],
) -> None:
    """Refuse a whole wave before any of it persists.

    The checks are the wave contract: the explore node must exist in the Run
    Graph snapshot, the wave fills exactly the declared width, the theses are
    divergent bets (no intra-wave duplicates, no empty bets), and none of them
    repeats a thesis an earlier wave already rejected.
    """
    if wave_index < 1:
        raise ExplorationContractError("wave_index starts at 1")
    graph_node_ids = {node.node_id for node in run.graph.materialize().nodes}
    if parent_node_id not in graph_node_ids:
        raise ThesisNotInWaveError(
            f"explore node {parent_node_id!r} is not present in the Run Graph snapshot"
        )
    if len(theses) != plan.width:
        raise ThesisWidthMismatchError(
            f"wave {wave_index} declares width {plan.width} but was given {len(theses)} theses"
        )
    _require_divergent_theses(wave_index, theses)
    prior_rejected = {_normalize_thesis(thesis) for thesis in rejected_theses}
    for slot, thesis in enumerate(theses):
        if _normalize_thesis(thesis) in prior_rejected:
            raise DuplicateThesisError(
                f"wave {wave_index} slot {slot} repeats a thesis an earlier wave rejected"
            )


def _require_divergent_theses(wave_index: int, theses: Sequence[str]) -> None:
    """Refuse empty theses and two slots carrying the same bet."""
    seen: dict[str, int] = {}
    for slot, thesis in enumerate(theses):
        normalized = _normalize_thesis(thesis)
        if not normalized:
            raise ExplorationContractError(f"wave {wave_index} slot {slot} carries an empty thesis")
        if normalized in seen:
            raise DuplicateThesisError(
                f"wave {wave_index} theses {seen[normalized]} and {slot} are the same bet"
            )
        seen[normalized] = slot


async def fan_out_wave(
    store: ExplorationRunStore,
    run: Run,
    *,
    plan: ExplorationPlan,
    wave_index: int,
    parent_node_id: str,
    theses: Sequence[str],
    rejected_theses: Sequence[str] = (),
) -> list[NodeRun]:
    """Fan one explore wave out to ``plan.width`` thesis NodeRuns on ``run``.

    Validates the whole wave before persisting any of it, so a contract
    failure leaves no partial wave behind:

    - exactly ``plan.width`` theses (the pack declared the width; the wave
      fills it);
    - no intra-wave duplicates — the theses are divergent bets, not copies;
    - no thesis already in ``rejected_theses`` — repeating a rejected thesis
      is a contract failure (:class:`DuplicateThesisError`).

    The child NodeRuns stay on ``run`` — one canonical Run, no new Run
    identity per wave — and each carries its :class:`ThesisProvenance` under
    ``NodeRun.provenance[PROVENANCE_KEY]``.
    """
    _validate_wave_fanout(
        run,
        plan=plan,
        wave_index=wave_index,
        parent_node_id=parent_node_id,
        theses=theses,
        rejected_theses=rejected_theses,
    )

    created: list[NodeRun] = []
    for slot, thesis in enumerate(theses):
        provenance = ThesisProvenance(
            thesis=thesis,
            wave_index=wave_index,
            slot=slot,
            policy=plan.policy,
            width=plan.width,
            parent_node_id=parent_node_id,
            goal_revision=plan.goal_revision,
            rubric_revision=plan.rubric_revision,
        )
        created.append(
            await store.create_node_run(
                run.run_id,
                node_id=parent_node_id,
                provenance={
                    PROVENANCE_KEY: {
                        "thesis": provenance.model_dump(mode="json"),
                        "disposition": ThesisDisposition.PROPOSED.value,
                    }
                },
            )
        )
    return created


async def record_thesis_score(
    store: ExplorationRunStore,
    node_run_id: str,
    *,
    rubric_revision: str,
    score: float,
    rationale: str = "",
) -> ThesisRecord:
    """Score one thesis against the Rubric revision it was emitted under.

    Eval-on-Run (#792) shape: the score is durable on the thesis NodeRun of
    the same Run, and it must name the *same* Rubric revision the wave was
    emitted under — scoring against any other Rubric revision is a contract
    failure (:class:`RubricRevisionMismatchError`).
    """
    node_run = await _require_thesis_node_run(store, node_run_id)
    provenance = thesis_provenance_of(node_run)
    assert provenance is not None
    existing = _thesis_record_of(node_run)
    if (
        existing.disposition in REJECTED_DISPOSITIONS
        or existing.disposition is ThesisDisposition.WINNER
    ):
        raise ThesisSettledError(
            f"thesis {provenance.thesis_id!r} of wave {provenance.wave_index} "
            f"is already {existing.disposition.value}"
        )
    if _normalize_thesis(rubric_revision) != _normalize_thesis(provenance.rubric_revision):
        raise RubricRevisionMismatchError(
            f"thesis {provenance.thesis_id!r} was emitted under Rubric "
            f"{provenance.rubric_revision!r}, not {rubric_revision!r}"
        )
    thesis_score = ThesisScore(
        rubric_revision=provenance.rubric_revision,
        score=score,
        rationale=rationale,
    )
    updated = await _merge_thesis_provenance(
        store,
        node_run_id,
        {
            "disposition": ThesisDisposition.SCORED.value,
            "score": thesis_score.model_dump(mode="json"),
        },
    )
    return _thesis_record_of(updated)


async def _require_wave_of_run(
    store: ExplorationRunStore,
    run_id: str,
    *,
    wave_index: int,
    node_run_id: str,
) -> list[ThesisRecord]:
    """The thesis records of one wave, refusing Runs, waves, or theses absent."""
    run = await store.get_run(run_id)
    if run is None:
        raise RunNotFound(run_id)
    records = {
        record.node_run_id: record for record in wave_records(await store.list_node_runs(run_id))
    }
    if node_run_id not in records:
        raise ThesisNotInWaveError(f"NodeRun {node_run_id!r} carries no thesis on Run {run_id!r}")
    wave = [record for record in records.values() if record.thesis.wave_index == wave_index]
    if not wave:
        raise ThesisNotInWaveError(f"wave {wave_index} has no theses on Run {run_id!r}")
    if node_run_id not in {record.node_run_id for record in wave}:
        raise ThesisNotInWaveError(f"NodeRun {node_run_id!r} is not part of wave {wave_index}")
    return wave


def _existing_winner(
    wave_index: int, wave: list[ThesisRecord], node_run_id: str
) -> ThesisRecord | None:
    """The wave's named winner, or ``None`` when none was named yet.

    Naming a *different* thesis after a winner exists is a contract failure;
    re-naming the sitting winner is the idempotent no-op it must be.
    """
    named = [record for record in wave if record.disposition is ThesisDisposition.WINNER]
    if not named:
        return None
    if named[0].node_run_id != node_run_id:
        raise WaveWinnerAlreadyNamedError(
            f"wave {wave_index} already named {named[0].node_run_id!r} its winner"
        )
    return named[0]


async def _settle_wave_mates(
    store: ExplorationRunStore,
    wave: list[ThesisRecord],
    *,
    winner_node_run_id: str,
) -> None:
    """Mark every unsettled wave-mate of the new winner a loser."""
    for mate in wave:
        if mate.node_run_id == winner_node_run_id:
            continue
        if (
            mate.disposition in REJECTED_DISPOSITIONS
            or mate.disposition is ThesisDisposition.WINNER
        ):
            continue
        await _merge_thesis_provenance(
            store, mate.node_run_id, {"disposition": ThesisDisposition.LOSER.value}
        )


async def name_wave_winner(
    store: ExplorationRunStore,
    run_id: str,
    *,
    wave_index: int,
    node_run_id: str,
) -> ThesisRecord:
    """Name one thesis of a wave the winner; its wave-mates become losers.

    Losers remain queryable NodeRuns on the same Run — naming a winner
    settles a wave, it does not delete its history.
    """
    wave = await _require_wave_of_run(store, run_id, wave_index=wave_index, node_run_id=node_run_id)
    sitting_winner = _existing_winner(wave_index, wave, node_run_id)
    if sitting_winner is not None:
        return sitting_winner

    await _merge_thesis_provenance(
        store, node_run_id, {"disposition": ThesisDisposition.WINNER.value}
    )
    await _settle_wave_mates(store, wave, winner_node_run_id=node_run_id)
    winner_node_run = await _require_thesis_node_run(store, node_run_id)
    return _thesis_record_of(winner_node_run)


def merge_thesis_record(current: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Compose the next ``PROVENANCE_KEY`` value from the current one.

    The nested ``thesis`` identity may only be re-written with the values it
    already carries: a settled wave's theses are historical record. Anything
    else (disposition, score) progresses forward through the eval/fence
    lifecycle. Every domain write composes its record through this function,
    so no wave — later or concurrent — can rewrite what an earlier wave bet.
    """
    merged = dict(current)
    for key, value in patch.items():
        if key == "thesis" and key in merged and merged[key] != value:
            raise ThesisSettledError("thesis identity is immutable once recorded")
        merged[key] = value
    return merged


async def _merge_thesis_provenance(
    store: ExplorationRunStore,
    node_run_id: str,
    patch: dict[str, Any],
) -> NodeRun:
    node_run = await _require_thesis_node_run(store, node_run_id)
    current = _wave_record_of(node_run)
    merged = merge_thesis_record(current, patch)
    return await store.record_node_run_provenance(node_run_id, patch={PROVENANCE_KEY: merged})


async def _require_thesis_node_run(store: ExplorationRunStore, node_run_id: str) -> NodeRun:
    node_run = await store.get_node_run(node_run_id)
    if node_run is None:
        raise NodeRunNotFound(node_run_id)
    if node_run.provenance.get(PROVENANCE_KEY) is None:
        raise ThesisNotInWaveError(f"NodeRun {node_run_id!r} carries no {PROVENANCE_KEY!r} record")
    return node_run


__all__ = [
    "PROVENANCE_KEY",
    "REJECTED_DISPOSITIONS",
    "RUN_PROVENANCE_KEY",
    "DuplicateThesisError",
    "ExplorationContractError",
    "ExplorationPlan",
    "ExplorationPolicy",
    "ExplorationRunStore",
    "RubricRevisionMismatchError",
    "ThesisDisposition",
    "ThesisNotInWaveError",
    "ThesisProvenance",
    "ThesisRecord",
    "ThesisScore",
    "ThesisSettledError",
    "ThesisWidthMismatchError",
    "WaveWinnerAlreadyNamedError",
    "exploration_plan_of",
    "fan_out_wave",
    "merge_thesis_record",
    "name_wave_winner",
    "record_thesis_score",
    "rejected_thesis_texts",
    "thesis_provenance_of",
    "wave_records",
]
