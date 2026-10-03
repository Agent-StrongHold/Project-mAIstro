"""Retrodiction prefilter (M4-A5): versioned/addressable prior-trace replay
in front of expensive sandbox/frontier evaluation.

Covers the five acceptance behaviors:

1. Prior traces are versioned/addressable and replay is deterministic
   (TraceLedger + genome_fingerprint).
2. Every decision records WHY a candidate was rejected, deprioritized, or
   allowed onward (PrefilterDecision.reasons with trace-id evidence).
3. False-negative risk is measured against candidates that later succeed in
   full evaluation (PrefilterStats.observe_outcome, shadow mode).
4. Promotion still requires the real current evaluator/sandbox path plus the
   human approval gate — the prefilter never grants it.
5. Cost/runtime saved by the filter is measured (evals_saved /
   cost_saved_usd / runtime_saved_seconds).
"""

from __future__ import annotations

import pytest

from maistro_evolve.audit import GenomeAuditTrail
from maistro_evolve.cycle import EvolutionConfig, EvolutionCycle
from maistro_evolve.diversity import _random_genome
from maistro_evolve.fitness import hard_gate_threshold
from maistro_evolve.harness import EvalHarness
from maistro_evolve.hyper_mutator import hyper_mutate, parse_fixer_proposal, spawn_fixer_challenger
from maistro_evolve.population import PopulationStore
from maistro_evolve.reflect import _evaluate_candidates, spawn_challenger
from maistro_evolve.retrodiction import (
    PrefilterConfig,
    RetrodictionPrefilter,
    TraceLedger,
    genome_fingerprint,
)
from maistro_evolve.types import DAGTopology, EvalResult, EvalWeights, NodeGenome, PipelineGenome

_BENCHES = ["proxy_ifeval", "proxy_bfcl"]


def _genome(name: str = "test", prompt: str = "test", model: str = "gpt-4") -> PipelineGenome:
    from datetime import UTC, datetime

    now = datetime.now(UTC).isoformat()
    return PipelineGenome(
        id=f"g-{name}",
        name=name,
        topology=DAGTopology(
            nodes=[
                NodeGenome(
                    id="q1",
                    role="queen",
                    strategy="react",
                    model=model,
                    temperature=0.3,
                    max_tokens=4096,
                    system_prompt=prompt,
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
        created_at=now,
        updated_at=now,
    )


class _CountingHarness(EvalHarness):
    """Real EvalHarness with deterministic fake runners that count calls."""

    def __init__(self, score: float = 0.0, cost_usd: float = 0.01, duration: float = 1.5) -> None:
        super().__init__()
        self._benchmarks.clear()
        self.calls = 0
        self.score = score
        self.cost_usd = cost_usd
        self.duration = duration
        for name in _BENCHES:
            self.register_benchmark(name, self._make_runner(name))

    def _make_runner(self, bench_name: str):
        async def runner(genome: PipelineGenome, llm_call: object) -> EvalResult:
            self.calls += 1
            return EvalResult(
                benchmark=bench_name,
                score=self.score,
                cost_usd=self.cost_usd,
                duration_seconds=self.duration,
                samples_evaluated=1,
                metadata={"fidelity": "proxy"},
            )

        return runner


def _failing_results(cost_usd: float = 0.01, duration: float = 1.5) -> list[EvalResult]:
    return [
        EvalResult(
            benchmark=b,
            score=0.0,
            cost_usd=cost_usd,
            duration_seconds=duration,
            samples_evaluated=1,
            metadata={"fidelity": "proxy"},
        )
        for b in _BENCHES
    ]


def _passing_traces(ledger: TraceLedger, genome: PipelineGenome, score: float = 0.5) -> None:
    ledger.record(
        genome,
        [
            EvalResult(
                benchmark=b,
                score=score,
                cost_usd=0.01,
                duration_seconds=1.5,
                samples_evaluated=1,
                metadata={"fidelity": "proxy"},
            )
            for b in _BENCHES
        ],
    )


# --------------------------------------------------------------------------- #
# 1. Versioned/addressable traces + deterministic replay
# --------------------------------------------------------------------------- #


def test_fingerprint_is_deterministic_and_payload_sensitive() -> None:
    a = _genome("one", prompt="p")
    b = _genome("two", prompt="p")  # different id/name/timestamps, same payload
    assert genome_fingerprint(a) == genome_fingerprint(b)

    mutated = _genome("three", prompt="DIFFERENT")
    assert genome_fingerprint(mutated) != genome_fingerprint(a)

    # Node list order is normalized: same topology built "in a different order".
    reordered = a.model_copy(deep=True)
    reordered.topology.nodes = list(reversed(reordered.topology.nodes))
    assert genome_fingerprint(reordered) == genome_fingerprint(a)

    # Scoring config (eval_weights) is not behavior: changing it must not
    # fork the fingerprint (retrodictions compare harness outcomes).
    reweighted = a.model_copy(deep=True)
    reweighted.eval_weights = reweighted.eval_weights.model_copy(update={"proxy_ifeval": 0.9})
    assert genome_fingerprint(reweighted) == genome_fingerprint(a)


def test_ledger_traces_are_addressable_and_stub_evidence_is_refused() -> None:
    ledger = TraceLedger()
    g = _genome("one")
    assert ledger.schema_version == 1

    recorded = ledger.record(g, _failing_results())
    assert len(recorded) == 2
    assert len(ledger) == 2
    # Addressable by trace_id...
    for trace in recorded:
        fetched = ledger.get(trace.trace_id)
        assert fetched is not None
        assert fetched.genome_fingerprint == genome_fingerprint(g)
        assert fetched.schema_version == 1
    # ...and by fingerprint + benchmark.
    assert len(ledger.traces_for(genome_fingerprint(g), "proxy_ifeval")) == 1

    # SPEC-202: stub results are noise — recording them must be refused so
    # they can never drive a rejection.
    before = len(ledger)
    stubbed = ledger.record(
        g,
        [EvalResult(benchmark="proxy_ifeval", score=0.9, metadata={"stub": True})],
    )
    assert stubbed == []
    assert len(ledger) == before


def test_replay_is_deterministic_and_returns_latest_trace_per_benchmark() -> None:
    ledger = TraceLedger()
    g = _genome("one")
    ledger.record(g, [EvalResult(benchmark="proxy_ifeval", score=0.2)])
    ledger.record(g, [EvalResult(benchmark="proxy_ifeval", score=0.8)])

    first = ledger.replay(g, _BENCHES)
    assert first["proxy_ifeval"].score == 0.8  # latest sample wins
    assert ledger.replay(g, _BENCHES) == first  # unchanged ledger ⇒ identical replay

    # History is preserved and every sample stays addressable.
    traces = ledger.traces_for(genome_fingerprint(g), "proxy_ifeval")
    assert [t.score for t in traces] == [0.2, 0.8]
    assert len({t.trace_id for t in traces}) == 2

    # A different payload has no evidence to replay.
    assert ledger.replay(_genome("two", prompt="other"), _BENCHES) == {}


# --------------------------------------------------------------------------- #
# 2. Recorded decisions: reject / deprioritize / allow with reasons
# --------------------------------------------------------------------------- #


def test_decide_allows_candidates_without_prior_evidence() -> None:
    ledger = TraceLedger()
    prefilter = RetrodictionPrefilter(ledger)
    decision = prefilter.decide(_genome("novel"), _BENCHES)
    assert decision.verdict == "allow"
    assert [r.code for r in decision.reasons] == ["no_prior_evidence"]
    assert decision.predicted_scores == {}
    assert decision.evals_saved == 0
    assert prefilter.stats.allowed == 1


def test_decide_rejects_known_total_failure_repeat_with_trace_evidence() -> None:
    ledger = TraceLedger()
    prior = _genome("prior", prompt="p")
    ledger.record(prior, _failing_results())
    candidate = _genome("candidate", prompt="p")  # same payload, fresh id

    prefilter = RetrodictionPrefilter(ledger)
    decision = prefilter.decide(candidate, _BENCHES)

    assert decision.verdict == "reject"
    assert [r.code for r in decision.reasons] == ["prior_total_failure"]
    # The rejection cites the exact prior evidence, addressable in the ledger.
    assert len(decision.reasons[0].trace_ids) == 2
    assert all(ledger.get(tid) is not None for tid in decision.reasons[0].trace_ids)
    assert decision.predicted_scores == {"proxy_ifeval": 0.0, "proxy_bfcl": 0.0}
    # Measured savings: the full repeated eval this verdict skips.
    assert decision.evals_saved == 2
    assert decision.cost_saved_usd == pytest.approx(0.02)
    assert decision.runtime_saved_seconds == pytest.approx(3.0)
    assert prefilter.stats.rejected == 1
    assert prefilter.stats.evals_saved == 2
    assert prefilter.stats.cost_saved_usd == pytest.approx(0.02)
    assert prefilter.stats.runtime_saved_seconds == pytest.approx(3.0)


def test_decide_deprioritizes_unscored_duplicate_of_evaluated_payload() -> None:
    ledger = TraceLedger()
    _passing_traces(ledger, _genome("prior", prompt="p"))
    candidate = _genome("candidate", prompt="p")  # no eval_scores yet

    prefilter = RetrodictionPrefilter(ledger)
    decision = prefilter.decide(candidate, _BENCHES)

    # The copy still needs real scores to survive culling, so it is triaged
    # (evaluated last), never skipped: rejecting here would strand it unscored.
    assert decision.verdict == "deprioritize"
    assert [r.code for r in decision.reasons] == ["duplicate_of_scored_payload"]
    assert decision.evals_saved == 0
    assert prefilter.stats.deprioritized == 1
    assert prefilter.stats.evals_saved == 0


def test_decide_deprioritizes_repeat_of_already_scored_genome() -> None:
    ledger = TraceLedger()
    scored = _genome("scored", prompt="p")
    _passing_traces(ledger, scored)
    scored.eval_scores = {"proxy_ifeval": 0.5, "proxy_bfcl": 0.5}

    prefilter = RetrodictionPrefilter(ledger)
    decision = prefilter.decide(scored, _BENCHES)

    assert decision.verdict == "deprioritize"
    assert [r.code for r in decision.reasons] == ["repeat_already_scored"]


def test_decide_partial_evidence_never_filters() -> None:
    ledger = TraceLedger()
    prior = _genome("prior", prompt="p")
    # Evidence for only ONE requested benchmark: a retrodiction cannot speak
    # for the uncovered one, so the candidate must run.
    ledger.record(
        prior,
        [EvalResult(benchmark="proxy_ifeval", score=0.0, cost_usd=0.01, duration_seconds=1.5)],
    )
    candidate = _genome("candidate", prompt="p")

    prefilter = RetrodictionPrefilter(ledger)
    decision = prefilter.decide(candidate, _BENCHES)

    assert decision.verdict == "allow"
    assert [r.code for r in decision.reasons] == ["partial_prior_evidence"]
    assert decision.predicted_scores == {"proxy_ifeval": 0.0}


def test_prefilter_off_config_semantics_via_stats_and_gate_thresholds() -> None:
    # The reject rule must key off the same gate table the real evaluator
    # enforces (no drifted private copy).
    assert hard_gate_threshold("proxy_ifeval") == pytest.approx(0.25)
    assert hard_gate_threshold("code_rsi") == pytest.approx(0.01)  # default floor


# --------------------------------------------------------------------------- #
# 3. Measured false-negative risk
# --------------------------------------------------------------------------- #


def test_false_negatives_measured_against_candidates_that_later_succeed() -> None:
    ledger = TraceLedger()
    _passing_traces(ledger, _genome("prior", prompt="p"))
    prefilter = RetrodictionPrefilter(ledger)

    # A deprioritized candidate whose full evaluation later SUCCEEDS is a
    # measured false negative.
    first = prefilter.decide(_genome("c1", prompt="p"), _BENCHES)
    assert first.verdict == "deprioritize"
    assert prefilter.observe_outcome(first, passed=True, genome_id="c1") is True
    # ...and one that fails was a correct triage, not a false negative.
    second = prefilter.decide(_genome("c2", prompt="p"), _BENCHES)
    assert prefilter.observe_outcome(second, passed=False, genome_id="c2") is False

    stats = prefilter.stats
    assert stats.filtered_outcomes_observed == 2
    assert stats.false_negatives == 1
    assert stats.false_negative_rate == pytest.approx(0.5)
    event = stats.false_negative_events[0]
    assert event["genome_id"] == "c1"
    assert event["verdict"] == "deprioritize"
    assert event["reason_codes"] == ["duplicate_of_scored_payload"]

    # Allowed candidates are never "observed outcomes" — the filter made no
    # claim about them.
    allowed = prefilter.decide(_genome("novel", prompt="fresh"), _BENCHES)
    assert prefilter.observe_outcome(allowed, passed=True) is False
    assert prefilter.stats.filtered_outcomes_observed == 2


def test_shadow_mode_records_reject_verdicts_without_filtering() -> None:
    ledger = TraceLedger()
    prior = _genome("prior", prompt="p")
    ledger.record(prior, _failing_results())
    candidate = _genome("candidate", prompt="p")

    prefilter = RetrodictionPrefilter(ledger, PrefilterConfig(mode="shadow"))
    decision = prefilter.decide(candidate, _BENCHES)

    # Same verdict the enforce mode would reach — but nothing is filtered.
    assert decision.verdict == "reject"
    assert decision.mode == "shadow"
    assert prefilter.would_filter(decision) is False
    assert prefilter.deprioritizes(decision) is False

    # Because shadow still evaluates everything, a would-be rejection that
    # later succeeds in full evaluation is directly observable as a false
    # negative — the measurement the enforce mode needs before it is trusted.
    assert prefilter.observe_outcome(decision, passed=True, genome_id=decision.genome_id) is True
    assert prefilter.stats.false_negative_rate == pytest.approx(1.0)


# --------------------------------------------------------------------------- #
# Cycle integration: enforcement, savings, shadow, off
# --------------------------------------------------------------------------- #


def _cycle_config(**overrides: object) -> EvolutionConfig:
    defaults: dict[str, object] = {
        "population_size": 2,
        "eval_batch_size": 2,
        "mutation_rate": 0.0,  # keep bred children byte-identical to parents
        "self_improve": False,
        "target_benchmarks": list(_BENCHES),
        # These tests isolate prefilter triage semantics; the orthogonal
        # per-cycle reconfirmation of already-evaluated genomes (#854) adds
        # fresh samples that would pollute the harness-call accounting.
        "reconfirm_per_cycle": 0,
    }
    defaults.update(overrides)
    return EvolutionConfig(**defaults)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_cycle_enforces_rejection_across_cycles_and_measures_savings() -> None:
    harness = _CountingHarness(score=0.0)  # failing payloads → reject-grade evidence
    cycle = EvolutionCycle(harness=harness)
    store = PopulationStore()
    store.add(_genome("a", prompt="alpha"))
    store.add(_genome("b", prompt="beta"))

    cfg = _cycle_config()
    await cycle.run_cycle(store, llm_call=None, config=cfg)
    assert harness.calls == 4  # both genomes x both benchmarks, first cycle
    assert len(cycle._ledger) == 4  # every real result became replayable evidence

    # Breeding (rate 0, identical parents) produced an unscored byte-identical
    # copy of the survivor. Its payload's prior traces all fail the gate, so
    # cycle 2 must reject it WITHOUT spending a single runner call.
    calls_before = harness.calls
    ledger_before = len(cycle._ledger)
    await cycle.run_cycle(store, llm_call=None, config=cfg)
    assert harness.calls == calls_before  # the expensive eval never happened

    children = [g for g in store.list_all() if not g.eval_scores]
    assert children, "expected the unscored duplicate to still be present"
    for child in children:
        recorded = child.harness_params["retrodiction"]
        assert recorded["verdict"] == "reject"
        assert recorded["mode"] == "enforce"
        assert recorded["reasons"][0]["code"] == "prior_total_failure"
        assert all(cycle._ledger.get(tid) for tid in recorded["reasons"][0]["trace_ids"])
        # No fabricated evidence: the gate-failure path leaves it scoreless
        # (fitness 0.0), so it cannot win a tournament or breed.
        assert child.eval_scores == {}
        assert child.fitness_score == 0.0

    stats = cycle.prefilter_stats
    assert stats is not None
    assert stats["candidates_seen"] == len(children)
    assert stats["rejected"] == len(children)
    assert stats["evals_saved"] == 2 * len(children)
    assert stats["cost_saved_usd"] == pytest.approx(0.02 * len(children))
    assert stats["runtime_saved_seconds"] == pytest.approx(3.0 * len(children))
    # A candidate the filter rejected in enforce mode is never evaluated, so
    # there is no observed outcome to count (and shadow mode is the tool for
    # measuring that risk).
    assert stats["filtered_outcomes_observed"] == 0
    assert stats["false_negative_rate"] is None
    assert len(cycle._ledger) == ledger_before  # rejected repeats record nothing


@pytest.mark.asyncio
async def test_cycle_shadow_mode_still_evaluates_and_reconciles_outcomes() -> None:
    harness = _CountingHarness(score=0.0)
    cycle = EvolutionCycle(harness=harness)
    store = PopulationStore()
    store.add(_genome("a", prompt="alpha"))
    store.add(_genome("b", prompt="beta"))

    await cycle.run_cycle(store, llm_call=None, config=_cycle_config())
    calls_before = harness.calls

    await cycle.run_cycle(store, llm_call=None, config=_cycle_config(retrodiction="shadow"))
    assert harness.calls > calls_before  # shadow never skips: it only measures

    decided = [
        g
        for g in store.list_all()
        if g.harness_params.get("retrodiction", {}).get("verdict") == "reject"
        and g.harness_params["retrodiction"]["mode"] == "shadow"
    ]
    assert decided  # the would-be-rejected copy was decided on...
    assert all(g.eval_scores for g in decided)  # ...but fully evaluated anyway

    stats = cycle.prefilter_stats
    assert stats is not None
    assert stats["rejected"] >= 1
    # The replayed evidence was right this time (score 0.0 fails the gate), so
    # the observed outcome reconciles as a true positive, not a false negative.
    assert stats["filtered_outcomes_observed"] >= 1
    assert stats["false_negatives"] == 0
    assert stats["false_negative_rate"] == 0.0


@pytest.mark.asyncio
async def test_cycle_off_mode_skips_prefilter_completely() -> None:
    harness = _CountingHarness(score=0.0)
    cycle = EvolutionCycle(harness=harness)
    store = PopulationStore()
    store.add(_genome("a", prompt="alpha"))
    store.add(_genome("b", prompt="beta"))

    await cycle.run_cycle(store, llm_call=None, config=_cycle_config(retrodiction="off"))
    calls_before = harness.calls
    await cycle.run_cycle(store, llm_call=None, config=_cycle_config(retrodiction="off"))

    assert cycle.prefilter_stats is None
    assert harness.calls > calls_before  # duplicates evaluated: no replay gate
    for g in store.list_all():
        assert "retrodiction" not in g.harness_params


# --------------------------------------------------------------------------- #
# 4. Promotion still requires the real evaluator path + human approval
# --------------------------------------------------------------------------- #


class _RecordingSink:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def log_delegation(self, peer_name: str, agent_id: str, detail: str) -> None:
        self.calls.append((peer_name, agent_id, detail))


@pytest.mark.asyncio
async def test_prefilter_never_grants_promotion_human_gate_still_required() -> None:
    harness = _CountingHarness(score=0.9)  # a "winning" payload
    cycle = EvolutionCycle(harness=harness)
    store = PopulationStore()
    store.add(_genome("a", prompt="alpha"))
    store.add(_genome("b", prompt="beta"))

    # Two cycles: the second deprioritizes/replays the bred duplicate — the
    # prefilter is fully exercised — yet nothing may reach live traffic.
    # Reconfirmation stays on here (#854): the champion API only surfaces
    # genomes with the independent-evidence floor met, and a champion must
    # exist for the human approval gate to refuse.
    cfg = _cycle_config(reconfirm_per_cycle=2)
    await cycle.run_cycle(store, llm_call=None, config=cfg)
    await cycle.run_cycle(store, llm_call=None, config=cfg)

    for g in store.list_all():
        assert g.approved_for_promotion is False
        assert g.is_active is False

    champion = store.get_champion()
    assert champion is not None
    audit = GenomeAuditTrail(_RecordingSink())
    with pytest.raises(PermissionError):
        await store.promote_audited(champion.id, audit)
    # The refusal itself is auditable (#854): the attempt is recorded, then
    # the human-gate rejection with its reasons.
    assert [e.event for e in audit.entries] == ["promotion_attempt", "promotion_rejected"]
    assert store.get_active() is None


# --------------------------------------------------------------------------- #
# Frontier-call verification paths (reflect / hyper-mutator)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_reflect_candidates_prefiltered_against_prior_traces() -> None:
    parent = _genome("parent", prompt="base")
    node: NodeGenome = parent.topology.nodes[0]

    ledger = TraceLedger()
    # A prior cycle already tried the exact proposal "same" and it scored
    # below the gate: replay must skip the repeat without a frontier spend.
    prior_challenger = spawn_challenger(parent, node.id, "same")
    ledger.record(
        prior_challenger,
        [EvalResult(benchmark="proxy_ifeval", score=0.0, cost_usd=0.05, duration_seconds=2.0)],
    )

    class _Harness:
        def __init__(self) -> None:
            self.calls = 0

        async def evaluate_genome(self, genome, benchmarks, llm_call=None):  # type: ignore[no-untyped-def]
            self.calls += 1
            return [
                EvalResult(
                    benchmark=benchmarks[0],
                    score=0.9,
                    cost_usd=0.03,
                    duration_seconds=1.0,
                    samples_evaluated=1,
                )
            ]

    harness = _Harness()
    prefilter = RetrodictionPrefilter(ledger)
    ledger_before = len(ledger)

    best, score, prompt = await _evaluate_candidates(
        ["same", "novel"], parent, node, "proxy_ifeval", harness, None, prefilter=prefilter
    )

    assert harness.calls == 1  # only the novel proposal was verified
    assert prompt == "novel"
    assert score == pytest.approx(0.9)
    assert best is not None
    # The novel verification became replayable evidence for later cycles.
    assert len(ledger) == ledger_before + 1


@pytest.mark.asyncio
async def test_hyper_mutate_skips_known_failure_proposals() -> None:
    g = _random_genome()
    entry = next(n for n in g.topology.nodes if n.id == g.topology.entry_node)
    assert entry.fixer is not None
    entry.fixer.tdd_rigor = 0.10
    g.eval_scores = {"code_rsi": 0.5}

    ledger = TraceLedger()
    # Prior evidence: the exact proposal {"tdd_rigor": 0.95} already failed.
    prior = spawn_fixer_challenger(g, parse_fixer_proposal('{"tdd_rigor": 0.95}', entry.fixer))
    ledger.record(
        prior, [EvalResult(benchmark="code_rsi", score=0.0, cost_usd=0.05, duration_seconds=2.0)]
    )

    class _Harness:
        def __init__(self) -> None:
            self.evaluated: list[str] = []

        async def evaluate_genome(self, genome, benchmarks, llm_call=None):  # type: ignore[no-untyped-def]
            self.evaluated.append(genome.id)
            return [EvalResult(benchmark=benchmarks[0], score=0.9, samples_evaluated=1)]

    harness = _Harness()
    prefilter = RetrodictionPrefilter(ledger)

    replies = iter(['{"tdd_rigor": 0.95}', '{"tdd_rigor": 0.80}'])

    async def llm_call(prompt: str) -> str:
        return next(replies)

    outcome = await hyper_mutate(
        g,
        harness,  # type: ignore[arg-type]
        llm_call,
        benchmarks=["code_rsi"],
        num_candidates=2,
        prefilter=prefilter,
    )

    assert outcome is not None and outcome.accepted
    assert outcome.best_candidate_score == pytest.approx(0.9)
    # Only the novel proposal reached the sandbox; the known-failure repeat
    # was replayed away.
    assert len(harness.evaluated) == 1
