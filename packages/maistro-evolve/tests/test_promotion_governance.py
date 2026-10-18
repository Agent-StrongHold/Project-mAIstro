"""Governed champion selection and promotion (#21, #854).

Each test pins one leg of the one canonical
candidate → independent evaluation → governed promotion contract:

- a lucky single sample is rejected pending fresh confirmation;
- best-of-N winners stay ineligible until post-acceptance confirmation;
- unevaluated candidates are excluded from selection/promotion and are not
  silently culled;
- gate-failing, unstable, stale, and unapproved candidates are excluded;
- a worse candidate can never replace a stronger incumbent because promote()
  was called later;
- a genuinely better, independently confirmed candidate CAN promote;
- evidence is bound to one immutable objective version;
- the EMA/repeated-sampling estimator is exercised by the real cycle.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from maistro_evolve.audit import GenomeAuditTrail
from maistro_evolve.cycle import EvolutionConfig, EvolutionCycle
from maistro_evolve.harness import EvalHarness
from maistro_evolve.population import PopulationStore
from maistro_evolve.promotion import (
    BEST_OF_N_KEY,
    PromotionPolicy,
    PromotionRecord,
    objective_version,
    promotion_eligibility,
    selection_eligibility,
)
from maistro_evolve.types import DAGTopology, EvalResult, EvalWeights, NodeGenome, PipelineGenome


def _genome(name: str, approved: bool = True) -> PipelineGenome:
    return PipelineGenome(
        id=f"g-{name}",
        name=name,
        topology=DAGTopology(
            nodes=[
                NodeGenome(
                    id="q1",
                    role="queen",
                    strategy="react",
                    model="gpt-4",
                    temperature=0.3,
                    max_tokens=4096,
                    system_prompt="test",
                    max_tool_rounds=5,
                )
            ],
            edges=[],
            entry_node="q1",
            max_cycles=3,
            beam_width=1,
            use_scout=False,
        ),
        eval_weights=EvalWeights(),
        created_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
        approved_for_promotion=approved,
    )


def _evidence(
    genome: PipelineGenome,
    score: float = 0.8,
    samples: int = 2,
    cycle: int = 1,
    obj: str = "objective-test",
    history: list[float] | None = None,
) -> PipelineGenome:
    genome.eval_scores = {"proxy_ifeval": score}
    genome.fitness_score = score
    genome.harness_params["eval_samples"] = {"proxy_ifeval": samples}
    genome.harness_params["eval_history"] = {
        "proxy_ifeval": history if history is not None else [score - 0.01, score + 0.01]
    }
    genome.harness_params["objective_version"] = obj
    genome.harness_params["evidence_cycle"] = cycle
    return genome


class _RecordingSink:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def log_delegation(self, peer_name: str, agent_id: str, detail: str) -> None:
        self.calls.append((peer_name, agent_id, detail))


# --- Acceptance 1/2/7: independent samples, confirmation, winner's curse -----


def test_lucky_single_sample_rejected_pending_confirmation() -> None:
    """One lucky first evaluation neither makes a champion nor promotes."""
    store = PopulationStore()
    lucky = _evidence(_genome("lucky"), score=0.99, samples=1)
    store.add(lucky)

    assert store.get_champion() is None  # selection refuses insufficient evidence

    report = selection_eligibility(lucky, PromotionPolicy())
    assert not report.eligible
    assert any("1 sample(s) < required 2" in r for r in report.reasons)

    trail = GenomeAuditTrail(_RecordingSink())
    with pytest.raises(PermissionError, match="governed promotion policy"):
        asyncio.run(store.promote_audited("g-lucky", trail))
    assert store.get_active() is None
    assert any(e.event == "promotion_rejected" for e in trail.entries)


def test_best_of_n_winner_blocked_until_fresh_confirmation() -> None:
    """A best-of-N winner (winner's curse) must gather a fresh sample beyond
    the round that selected it before it can activate."""
    genome = _evidence(_genome("bon"), score=0.9, samples=2)
    genome.harness_params[BEST_OF_N_KEY] = {
        "benchmark": "proxy_ifeval",
        "claimed_score": 0.9,
        "candidates": 5,
        "samples_at_acceptance": {"proxy_ifeval": 2},
    }
    policy = PromotionPolicy()
    report = selection_eligibility(genome, policy)
    assert not report.eligible
    assert any("pending fresh confirmation" in r for r in report.reasons)

    # A fresh, independent post-acceptance sample (the production cycle's
    # reconfirmation step folds it through the EMA) clears the guard.
    EvolutionCycle._fold_score(genome, "proxy_ifeval", 0.88, stub=False, alpha=0.5)
    assert genome.harness_params["eval_samples"]["proxy_ifeval"] == 3
    assert selection_eligibility(genome, policy).eligible

    # Opting out is explicit policy, never an accident of defaults.
    off = PromotionPolicy(require_confirmation_after_best_of_n=False)
    assert selection_eligibility(genome, off).eligible


def test_unstable_evidence_fails_uncertainty_bound() -> None:
    """Evidence swinging between samples ([0.9, 0.1]) is noise, not evidence."""
    genome = _evidence(_genome("swing"), score=0.5, history=[0.9, 0.1])
    report = selection_eligibility(genome, PromotionPolicy())
    assert not report.eligible
    assert any("unstable" in r for r in report.reasons)


# --- Acceptance 3/4: explicit eligibility for champion/promotion APIs --------


def test_unevaluated_candidate_excluded_and_not_silently_culled() -> None:
    """An unevaluated offspring is never a champion/promotion target, and is
    not culled merely because its score is absent (policy disposes only scored
    genomes)."""
    store = PopulationStore()
    unevaluated = _genome("offspring", approved=False)
    store.add(unevaluated)
    scored = _evidence(_genome("scored", approved=False), score=0.5)
    store.add(scored)

    # The unevaluated offspring is never the champion (the scored one is —
    # approval is a promotion gate, not a selection gate).
    assert store.get_champion() is scored
    store.cull_bottom(0.3)
    assert store.get("g-offspring") is not None  # not culled for lacking a score

    report = promotion_eligibility(unevaluated, None, PromotionPolicy())
    assert not report.eligible
    assert any("not evaluated" in r for r in report.reasons)
    assert any("not approved" in r for r in report.reasons)


def test_gate_failed_stale_and_mismatched_evidence_excluded() -> None:
    policy = PromotionPolicy()

    # Correctness/security gate failure: proxy_ifeval floor is 0.25.
    failed = _evidence(_genome("failed"), score=0.1)
    report = selection_eligibility(failed, policy)
    assert not report.eligible
    assert any("hard gate" in r for r in report.reasons)

    # Evidence older than the policy window is stale.
    stale = _evidence(_genome("stale"), score=0.8, cycle=0)
    assert not selection_eligibility(stale, policy, current_cycle=50).eligible
    assert selection_eligibility(stale, policy, current_cycle=5).eligible

    # Evidence stamped with a retired objective version is refused.
    pinned = PromotionPolicy(objective_versions=("objective-test",))
    migrated = _evidence(_genome("migrated"), obj="objective-old")
    assert not selection_eligibility(migrated, pinned).eligible


def test_approval_is_promotion_gate_not_selection_gate() -> None:
    """Champion APIs filter on evidence eligibility; the human approval gate
    binds at promotion ('approved-for-promotion where required')."""
    store = PopulationStore()
    unapproved = _evidence(_genome("unapproved"))
    unapproved.approved_for_promotion = False
    store.add(unapproved)

    assert store.get_champion() is unapproved

    report = promotion_eligibility(unapproved, None, PromotionPolicy())
    assert not report.eligible
    assert any("not approved" in r for r in report.reasons)


# --- Acceptance 5/6: incumbent comparison under one immutable objective ------


def test_worse_candidate_cannot_replace_stronger_incumbent() -> None:
    store = PopulationStore()
    incumbent = _evidence(_genome("incumbent"), score=0.9)
    worse = _evidence(_genome("worse"), score=0.5)  # approved, evidenced, but worse
    store.add(incumbent)
    store.add(worse)

    trail = GenomeAuditTrail(_RecordingSink())
    asyncio.run(store.promote_audited("g-incumbent", trail))
    assert store.get_active().id == "g-incumbent"

    later_trail = GenomeAuditTrail(_RecordingSink())
    with pytest.raises(PermissionError, match="required margin"):
        asyncio.run(store.promote_audited("g-worse", later_trail))

    assert store.get_active().id == "g-incumbent"  # incumbent still serving
    rejected = [e for e in later_trail.entries if e.event == "promotion_rejected"]
    assert len(rejected) == 1
    assert "does not beat" in rejected[0].detail


def test_promotion_refused_across_different_objective_versions() -> None:
    """Candidate and incumbent evidence must share one immutable objective."""
    store = PopulationStore()
    incumbent = _evidence(_genome("incumbent"), score=0.5, obj="objective-a")
    candidate = _evidence(_genome("better"), score=0.9, obj="objective-b")
    store.add(incumbent)
    store.add(candidate)
    asyncio.run(store.promote_audited("g-incumbent", GenomeAuditTrail(_RecordingSink())))

    with pytest.raises(PermissionError, match="objective mismatch"):
        asyncio.run(store.promote_audited("g-better", GenomeAuditTrail(_RecordingSink())))
    assert store.get_active().id == "g-incumbent"


def test_genuinely_better_confirmed_candidate_promotes() -> None:
    """The contract is not just a wall: an independently confirmed, approved,
    gate-passing candidate that beats the incumbent by the declared margin
    under the same objective DOES promote — with a complete decision record."""
    store = PopulationStore()
    incumbent = _evidence(_genome("incumbent"), score=0.5)
    candidate = _evidence(_genome("better"), score=0.9)
    store.add(incumbent)
    store.add(candidate)
    asyncio.run(store.promote_audited("g-incumbent", GenomeAuditTrail(_RecordingSink())))

    trail = GenomeAuditTrail(_RecordingSink())
    promoted = asyncio.run(store.promote_audited("g-better", trail))

    assert promoted.is_active is True
    assert incumbent.is_active is False
    assert store.get_active().id == "g-better"

    record = PromotionRecord.model_validate_json(trail.entries[-1].detail)
    assert record.candidate_id == "g-better"
    assert record.incumbent_id == "g-incumbent"
    assert record.resulting_active_id == "g-better"
    assert record.approved is True
    assert record.objective_version == "objective-test"
    assert record.incumbent_evidence is not None
    assert record.incumbent_evidence["fitness_score"] == pytest.approx(0.5)
    assert record.comparison["incumbent_fitness"] == pytest.approx(0.5)
    assert record.decision_rule["min_promotion_margin"] == (PromotionPolicy().min_promotion_margin)


def test_promotion_record_summary_names_the_decision() -> None:
    """The committed record renders as one operator-readable line naming the
    exact ids, objective, evidence, decision rule and approval (#854
    acceptance 8) — the same record the committed audit entry stores as JSON."""
    store = PopulationStore()
    incumbent = _evidence(_genome("incumbent"), score=0.5)
    candidate = _evidence(_genome("better"), score=0.9)
    store.add(incumbent)
    store.add(candidate)
    asyncio.run(store.promote_audited("g-incumbent", GenomeAuditTrail(_RecordingSink())))
    asyncio.run(store.promote_audited("g-better", GenomeAuditTrail(_RecordingSink())))

    record = store.last_promotion_record
    assert record is not None
    line = record.summary()
    assert "candidate g-better (fitness=0.9)" in line
    assert "incumbent g-incumbent (fitness=0.5)" in line
    assert "objective-test" in line
    assert "active now: g-better" in line
    assert "approved=True" in line
    assert f"min_promotion_margin={PromotionPolicy().min_promotion_margin}" in line

    # The rollback path reads the same record for operator context and keeps
    # the audit/compensation semantics intact (#342).
    rolled_back = asyncio.run(store.rollback_audited(GenomeAuditTrail(_RecordingSink())))
    assert rolled_back is not None and rolled_back.id == "g-incumbent"
    assert store.last_promotion_record is not None
    assert store.last_promotion_record.candidate_id == "g-better"


def test_objective_version_is_deterministic_and_sensitive() -> None:
    weights = EvalWeights()
    assert objective_version(["proxy_ifeval", "proxy_bfcl"], weights) == objective_version(
        ["proxy_bfcl", "proxy_ifeval"],
        weights,  # order-independent
    )
    assert objective_version(["proxy_ifeval"], weights) != objective_version(
        ["proxy_bfcl"], weights
    )
    heavier = weights.model_copy(update={"proxy_ifeval": 0.9})
    assert objective_version(["proxy_ifeval"], weights) != objective_version(
        ["proxy_ifeval"], heavier
    )


# --- Acceptance 2 (production cycle): EMA/repeated sampling actually runs ----


def _varying_harness(scores: list[float]) -> EvalHarness:
    """Deterministic harness returning the next score in `scores` per call."""
    harness = EvalHarness()
    harness._benchmarks.clear()
    calls = {"n": 0}

    async def runner(genome: PipelineGenome, llm_call: object) -> EvalResult:
        score = scores[min(calls["n"], len(scores) - 1)]
        calls["n"] += 1
        return EvalResult(benchmark="proxy_ifeval", score=score, metadata={})

    harness.register_benchmark("proxy_ifeval", runner)
    return harness


@pytest.mark.asyncio
async def test_production_cycle_repeats_evaluation_and_folds_ema() -> None:
    """The real cycle takes fresh samples of already-evaluated genomes, so the
    EMA estimator runs in production instead of a first sample being permanent.
    Fillers keep the population above cull_bottom's at-least-one floor."""
    cycle = EvolutionCycle(harness=_varying_harness([0.9, 0.1]))
    store = PopulationStore()
    cfg = EvolutionConfig(
        population_size=4,
        eval_batch_size=1,
        reconfirm_per_cycle=1,
        target_benchmarks=["proxy_ifeval"],
        self_improve=False,
    )
    for i in range(3):
        store.add(_evidence(_genome(f"filler{i}"), score=0.3, samples=3, cycle=0))
    store.add(_genome("g"))
    await cycle.run_cycle(store, config=cfg)

    genome = store.get("g-g")
    assert genome is not None
    # First sample 0.9, fresh confirmation sample 0.1 — EMA-folded, not overwritten.
    assert genome.harness_params["eval_samples"]["proxy_ifeval"] == 2
    assert genome.eval_scores["proxy_ifeval"] == pytest.approx(0.5)
    assert genome.harness_params["eval_history"]["proxy_ifeval"] == [0.9, 0.1]
    # Evidence is stamped with the objective and the cycle that produced it.
    assert genome.harness_params["objective_version"] == objective_version(["proxy_ifeval"])
    assert genome.harness_params["evidence_cycle"] == 0

    # Selection sees the unstable pair as noise: g's fitness (0.5) beats the
    # stable fillers (0.3), yet the champion is a FILLER — the swinging genome
    # is refused while the lower-fitness stable evidence is returned.
    champion = store.get_champion()
    assert champion is not None
    assert champion.id.startswith("g-filler")


@pytest.mark.asyncio
async def test_reconfirm_prioritizes_best_of_n_pending_then_stalest() -> None:
    """Reconfirmation order: pending best-of-N winners first, then fewest
    samples, then stalest evidence."""
    cycle = EvolutionCycle(harness=_varying_harness([0.5]))
    store = PopulationStore()
    cfg = EvolutionConfig(
        eval_batch_size=0,  # no first-evals; reconfirmation only
        reconfirm_per_cycle=2,
        target_benchmarks=["proxy_ifeval"],
        self_improve=False,
    )
    pending = _evidence(_genome("pending"), samples=2)
    pending.harness_params[BEST_OF_N_KEY] = {
        "benchmark": "proxy_ifeval",
        "samples_at_acceptance": {"proxy_ifeval": 2},
    }
    stale = _evidence(_genome("stale"), samples=3, cycle=0)
    fresh = _evidence(_genome("fresh"), samples=3, cycle=1)
    store.add(pending)
    store.add(stale)
    store.add(fresh)

    await cycle.run_cycle(store, config=cfg)

    assert pending.harness_params["eval_samples"]["proxy_ifeval"] == 3
    assert stale.harness_params["eval_samples"]["proxy_ifeval"] == 4
    assert fresh.harness_params["eval_samples"]["proxy_ifeval"] == 3  # untouched
    assert fresh.harness_params["evidence_cycle"] == 1  # not re-stamped either
