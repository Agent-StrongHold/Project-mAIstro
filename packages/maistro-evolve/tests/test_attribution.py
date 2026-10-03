"""M4-A8 producer attribution (#115): candidate lineage records the
generator/mutation/prompt/search operator that produced it (identity +
version), evaluation results credit those producers in an append-only ledger
without rewriting candidate history, productive operators can be favored with
a diversity-preserving exploration floor, negative credit is retained for
repeated regressions/failures, and attribution is auditable and scoped to
comparable evaluation contexts."""

from __future__ import annotations

import random
from datetime import UTC, datetime

import pytest

from maistro_evolve.attribution import (
    ATTRIBUTION_SCHEMA_VERSION,
    PRODUCER_VERSIONS,
    CandidateOrigin,
    CreditEvent,
    EvalContext,
    ProducerIdentity,
    ProducerKind,
    ProducerLedger,
    producer_identity,
    stamp_origin,
)
from maistro_evolve.crossover import crossover, crossover_and_mutate
from maistro_evolve.cycle import EvolutionConfig, EvolutionCycle
from maistro_evolve.harness import EvalHarness
from maistro_evolve.hyper_mutator import spawn_fixer_challenger
from maistro_evolve.mutate import (
    MUTATION_OPERATOR_NAMES,
    mutate_all,
    mutate_node,
    mutate_prompt,
    mutate_selected,
    mutate_topology,
)
from maistro_evolve.population import PopulationStore
from maistro_evolve.reflect import spawn_challenger
from maistro_evolve.types import (
    DAGTopology,
    EvalResult,
    EvalWeights,
    NodeGenome,
    PipelineGenome,
)

_REAL_CONTEXT = EvalContext(fidelity="real", benchmarks=("ifeval",), scope="run-1")


def _genome(name: str = "base", *, fixer: bool = False) -> PipelineGenome:
    node = NodeGenome(
        id="q1",
        role="queen",
        strategy="react",
        model="gpt-4",
        temperature=0.3,
        max_tokens=4096,
        system_prompt="test prompt.",
        max_tool_rounds=5,
    )
    if fixer:
        from maistro_evolve.fixer_genome import FixerGenome

        node.fixer = FixerGenome()
    return PipelineGenome(
        id=f"g-{name}",
        name=name,
        topology=DAGTopology(
            nodes=[node],
            edges=[],
            entry_node="q1",
            max_cycles=3,
            beam_width=1,
            use_scout=False,
        ),
        eval_weights=EvalWeights(),
        eval_scores={"proxy_ifeval": 0.5},
        created_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
    )


# --------------------------------------------------------------------------
# AC1: candidate lineage records generator/operator identity and version
# --------------------------------------------------------------------------


class TestOriginStamping:
    @pytest.mark.parametrize(
        ("operator", "producer_name"),
        [
            (mutate_topology, "mutate_topology"),
            (mutate_node, "mutate_node"),
            (mutate_prompt, "mutate_prompt"),
        ],
    )
    def test_mutation_children_record_operator_identity_and_version(
        self, operator, producer_name
    ) -> None:
        genome = _genome()
        child = operator(genome, 1.0)
        assert child.origin is not None
        assert child.origin.producer.kind is ProducerKind.MUTATION_OPERATOR
        assert child.origin.producer.name == producer_name
        assert child.origin.producer.version == PRODUCER_VERSIONS[producer_name]
        assert child.origin.parents == (genome.id,)
        assert child.origin.chain == (child.origin.producer.key(),)
        # Credit baseline: the parent's stored scores at production time.
        assert child.origin.baseline_scores == {"proxy_ifeval": 0.5}

    def test_unregistered_producer_fails_closed(self) -> None:
        with pytest.raises(KeyError, match="not registered"):
            producer_identity("operator_nobody_registered", ProducerKind.MUTATION_OPERATOR)

    def test_origin_context_is_recorded(self) -> None:
        child = mutate_prompt(_genome(), 1.0, origin_context=_REAL_CONTEXT)
        assert child.origin is not None
        assert child.origin.context == _REAL_CONTEXT

    def test_mutate_all_stamps_composite_origin(self) -> None:
        child = mutate_all(_genome(), 0.3)
        assert child.name.endswith("-all-mut")
        assert child.origin is not None
        assert child.origin.producer.name == "mutate_all"
        for component in MUTATION_OPERATOR_NAMES:
            assert component in (child.origin.note or "")

    def test_crossover_child_records_generator_origin(self) -> None:
        a, b = _genome("a"), _genome("b")
        a.eval_scores = {"proxy_ifeval": 0.4}
        b.eval_scores = {"proxy_ifeval": 0.7}
        child = crossover(a, b)
        assert child.origin is not None
        assert child.origin.producer.kind is ProducerKind.GENERATOR
        assert child.origin.producer.name == "crossover"
        assert child.origin.parents == (a.id, b.id)
        # Baseline is the better parent's stored score: beating it is what
        # earns crossover positive credit.
        assert child.origin.baseline_scores == {"proxy_ifeval": 0.7}

    def test_crossover_and_mutate_records_chain_and_upstream(self) -> None:
        a, b = _genome("a"), _genome("b")
        child = crossover_and_mutate(a, b, 0.3)
        assert child.origin is not None
        assert child.origin.producer.name == "mutate_all"
        assert child.origin.upstream == (a.id, b.id)
        assert child.origin.chain == (
            producer_identity("crossover", ProducerKind.GENERATOR).key(),
            child.origin.producer.key(),
        )

    def test_mutate_selected_records_applied_subset(self) -> None:
        child = mutate_selected(_genome(), 0.5, operators=("mutate_prompt", "mutate_node"))
        assert child.name.endswith("-sel-prompt-node-mut")
        assert child.origin is not None
        assert child.origin.producer.name == "mutate_selected"
        assert child.origin.note == "components: mutate_prompt, mutate_node"

    def test_mutate_selected_rejects_unknown_operator(self) -> None:
        with pytest.raises(ValueError, match="unknown mutation operator"):
            mutate_selected(_genome(), 0.5, operators=("mutate_prompt", "mutate_soul"))

    def test_mutate_selected_rejects_empty_subset(self) -> None:
        with pytest.raises(ValueError, match="at least one operator"):
            mutate_selected(_genome(), 0.5, operators=[])

    def test_reflect_challenger_records_prompt_operator(self) -> None:
        child = spawn_challenger(_genome(), "q1", "new and improved prompt.")
        assert child.origin is not None
        assert child.origin.producer.kind is ProducerKind.PROMPT_OPERATOR
        assert child.origin.producer.name == "reflective_improve"
        assert child.origin.parents == (_genome.__name__ and "g-base",)

    def test_hyper_challenger_records_search_operator(self) -> None:
        child = spawn_fixer_challenger(
            _genome(fixer=True), _genome(fixer=True).topology.nodes[0].fixer
        )
        assert child.origin is not None
        assert child.origin.producer.kind is ProducerKind.SEARCH_OPERATOR
        assert child.origin.producer.name == "hyper_mutator"

    def test_stamp_origin_is_once_only(self) -> None:
        genome = _genome()
        origin = CandidateOrigin(producer=producer_identity("seed", ProducerKind.GENERATOR))
        stamped = stamp_origin(genome, origin)
        assert stamped.origin == origin
        # Idempotent restamp with the equal origin is a no-op.
        assert stamp_origin(stamped, origin) is stamped
        # Rewriting with a different origin is refused.
        with pytest.raises(ValueError, match="never rewritten"):
            stamp_origin(stamped, CandidateOrigin(producer=origin.producer, note="different"))

    def test_schema_version_declared(self) -> None:
        assert ATTRIBUTION_SCHEMA_VERSION == "1"

    def test_origin_survives_persistence_roundtrip(self, tmp_path) -> None:
        store = PopulationStore(tmp_path / "pop.db")
        child = mutate_prompt(_genome(), 1.0, origin_context=_REAL_CONTEXT)
        store.add(child)
        loaded = store.get(child.id)
        assert loaded is not None
        assert loaded.origin == child.origin


# --------------------------------------------------------------------------
# AC2: evaluation results update producer statistics without rewriting
# candidate history
# --------------------------------------------------------------------------


class TestCredit:
    def _ledger_with_child(self) -> tuple[ProducerLedger, PipelineGenome]:
        ledger = ProducerLedger()
        child = mutate_prompt(_genome(), 1.0)
        ledger.register_candidate(child)
        return ledger, child

    def test_credit_classification_and_stats(self) -> None:
        ledger, child = self._ledger_with_child()
        context = EvalContext.from_harness(EvalHarness(), ["proxy_ifeval"])
        # Baseline is 0.5 → 0.7 improves, 0.3 regresses, 0.5 is neutral.
        assert ledger.credit(child, "proxy_ifeval", 0.7, context=context).outcome == "improvement"
        assert ledger.credit(child, "proxy_ifeval", 0.3, context=context).outcome == "regression"
        assert ledger.credit(child, "proxy_ifeval", 0.5, context=context).outcome == "neutral"
        stats = ledger.stats(
            producer_identity("mutate_prompt", ProducerKind.MUTATION_OPERATOR), context.key()
        )
        assert stats is not None
        assert (stats.attempts, stats.improvements, stats.regressions, stats.neutral) == (
            3,
            1,
            1,
            1,
        )
        assert stats.total_delta == pytest.approx(0.0)
        assert stats.last_delta == 0.0

    def test_credit_without_baseline_is_neutral_without_delta(self) -> None:
        ledger = ProducerLedger()
        child = mutate_prompt(_genome(), 1.0)
        child.origin = child.origin.model_copy(update={"baseline_scores": {}})
        ledger.register_candidate(child)
        event = ledger.credit(child, "proxy_bfcl", 0.9, context=EvalContext())
        assert event is not None
        assert event.outcome == "neutral"
        assert event.delta is None and event.baseline is None

    def test_credit_does_not_rewrite_candidate_history(self) -> None:
        ledger, child = self._ledger_with_child()
        context = EvalContext()
        origin_before = child.origin
        parents_before = (child.parent_a_id, child.parent_b_id)
        id_before = child.id
        for score in (0.9, 0.1, 0.5, 0.8):
            ledger.credit(child, "proxy_ifeval", score, context=context)
        # The candidate's own history is untouched by crediting.
        assert child.origin == origin_before
        assert (child.parent_a_id, child.parent_b_id) == parents_before
        assert child.id == id_before
        # The ledger side is append-only with strict sequence numbers.
        sequences = [e.sequence for e in ledger.events]
        assert sequences == [1, 2, 3, 4]
        assert all(isinstance(e, CreditEvent) for e in ledger.events)

    def test_credit_unknown_candidate_is_ignored(self) -> None:
        ledger = ProducerLedger()
        seed = _genome("seed")
        seed.origin = None
        assert ledger.credit(seed, "proxy_ifeval", 0.9, context=EvalContext()) is None
        assert ledger.events == ()

    def test_rewrite_registration_refused(self) -> None:
        ledger, child = self._ledger_with_child()
        assert ledger.register_candidate(child) is not None  # idempotent
        impostor = child.model_copy(update={"id": child.id})
        assert impostor.origin is not None
        rewritten = impostor.model_copy(
            update={"origin": impostor.origin.model_copy(update={"note": "forged"})}
        )
        with pytest.raises(ValueError, match="cannot be rewritten"):
            ledger.register_candidate(rewritten)

    def test_cycle_evaluation_credits_producer(self) -> None:
        harness = EvalHarness()
        harness._benchmarks.clear()

        async def fake_runner(genome: PipelineGenome, llm_call: object) -> EvalResult:
            return EvalResult(benchmark="proxy_ifeval", score=0.9, samples_evaluated=1)

        harness.register_benchmark("proxy_ifeval", fake_runner)
        cycle = EvolutionCycle(harness=harness)
        store = PopulationStore()
        parent = _genome("parent")
        store.add(parent)
        child = mutate_prompt(parent, 1.0)  # baseline 0.5 → 0.9 is an improvement
        store.add(child)
        config = EvolutionConfig(
            target_benchmarks=["proxy_ifeval"],
            eval_batch_size=5,
            cull_pct=0.0,
            reconfirm_per_cycle=0,  # one verified sample per genome: pure first-eval credit
        )
        import asyncio

        asyncio.run(cycle.run_cycle(store, llm_call=None, config=config))
        producer = producer_identity("mutate_prompt", ProducerKind.MUTATION_OPERATOR)
        stats = cycle.ledger.stats(producer, cycle._eval_context(config).key())
        assert stats is not None
        assert stats.improvements == 1
        # The unattributable seed parent produced no credit events.
        assert len(cycle.ledger.events) == 1
        assert cycle.ledger.events[0].candidate_id == child.id

    def test_cycle_reconfirmation_also_credits_producer(self) -> None:
        """#854 reconfirmation shares the M4-A8 crediting path: every fresh
        verified sample of a candidate is additional evidence about the
        producer that built it, APPENDED to the ledger — attempts accumulate,
        candidate history is never rewritten."""
        harness = EvalHarness()
        harness._benchmarks.clear()

        async def fake_runner(genome: PipelineGenome, llm_call: object) -> EvalResult:
            return EvalResult(benchmark="proxy_ifeval", score=0.9, samples_evaluated=1)

        harness.register_benchmark("proxy_ifeval", fake_runner)
        cycle = EvolutionCycle(harness=harness)
        store = PopulationStore()
        parent = _genome("parent")
        store.add(parent)
        child = mutate_prompt(parent, 1.0)  # baseline 0.5 → 0.9 is an improvement
        store.add(child)
        config = EvolutionConfig(
            target_benchmarks=["proxy_ifeval"],
            eval_batch_size=5,
            cull_pct=0.0,
            reconfirm_per_cycle=2,  # default policy: re-sample weakest/oldest evidence
        )
        import asyncio

        asyncio.run(cycle.run_cycle(store, llm_call=None, config=config))
        producer = producer_identity("mutate_prompt", ProducerKind.MUTATION_OPERATOR)
        stats = cycle.ledger.stats(producer, cycle._eval_context(config).key())
        assert stats is not None
        # First eval + one #854 reconfirmation of the child: two appended
        # credit events for the same producer and candidate. (The reconfirmed
        # seed parent stays unattributable and emits nothing.)
        assert stats.attempts == 2
        assert stats.improvements == 2
        assert [e.candidate_id for e in cycle.ledger.events] == [child.id, child.id]

    def test_cycle_attribution_disabled_records_nothing(self) -> None:
        harness = EvalHarness()
        harness._benchmarks.clear()

        async def fake_runner(genome: PipelineGenome, llm_call: object) -> EvalResult:
            return EvalResult(benchmark="proxy_ifeval", score=0.9, samples_evaluated=1)

        harness.register_benchmark("proxy_ifeval", fake_runner)
        cycle = EvolutionCycle(harness=harness)
        store = PopulationStore()
        store.add(mutate_prompt(_genome("parent"), 1.0))
        config = EvolutionConfig(
            target_benchmarks=["proxy_ifeval"],
            eval_batch_size=5,
            cull_pct=0.0,
            producer_attribution=False,
        )
        import asyncio

        asyncio.run(cycle.run_cycle(store, llm_call=None, config=config))
        assert cycle.ledger.events == ()


# --------------------------------------------------------------------------
# AC3: productive operators favored while preserving diversity
# --------------------------------------------------------------------------


class TestOperatorFavoring:
    def _context(self) -> EvalContext:
        return EvalContext.from_harness(EvalHarness(), ["proxy_ifeval"])

    def test_productive_operator_outranks_unproductive(self) -> None:
        ledger = ProducerLedger()
        context_key = self._context().key()
        bad = producer_identity("mutate_topology", ProducerKind.MUTATION_OPERATOR)
        for _ in range(5):
            ledger.credit_rejected_proposal(
                bad, self._context(), "proxy_ifeval", baseline=0.9, score=0.1
            )
        child = mutate_prompt(_genome(), 1.0)
        ledger.register_candidate(child)
        for _ in range(5):
            ledger.credit(child, "proxy_ifeval", 0.9, context=self._context())
        weights = ledger.operator_weights(
            MUTATION_OPERATOR_NAMES, context_key, kind=ProducerKind.MUTATION_OPERATOR
        )
        assert weights["mutate_prompt"] > weights["mutate_topology"]
        # Untried operators get the neutral prior, not a zero weight.
        assert weights["mutate_node"] > 0.0

    def test_exploration_floor_preserves_diversity(self) -> None:
        ledger = ProducerLedger(exploration_floor=0.4)
        context_key = self._context().key()
        child = mutate_prompt(_genome(), 1.0)
        ledger.register_candidate(child)
        for _ in range(50):
            ledger.credit(child, "proxy_ifeval", 1.0, context=self._context())
        weights = ledger.operator_weights(
            MUTATION_OPERATOR_NAMES, context_key, kind=ProducerKind.MUTATION_OPERATOR
        )
        per_name_floor = 0.4 / len(MUTATION_OPERATOR_NAMES)
        for name in MUTATION_OPERATOR_NAMES:
            assert weights[name] >= per_name_floor - 1e-9
        # Even the dominant operator cannot take more than the floored share.
        assert weights["mutate_prompt"] <= 1.0 - 0.4 + per_name_floor + 1e-9

    def test_select_operator_randomizes_within_weights(self) -> None:
        ledger = ProducerLedger(exploration_floor=0.4)
        context_key = self._context().key()
        child = mutate_prompt(_genome(), 1.0)
        ledger.register_candidate(child)
        for _ in range(20):
            ledger.credit(child, "proxy_ifeval", 1.0, context=self._context())
        rng = random.Random(7)
        picks = {
            ledger.select_operator(
                MUTATION_OPERATOR_NAMES,
                context_key,
                kind=ProducerKind.MUTATION_OPERATOR,
                rng=rng,
            )
            for _ in range(200)
        }
        # Diversity preserved: the floored mass keeps every operator reachable.
        assert picks == set(MUTATION_OPERATOR_NAMES)

    def test_repeated_regressor_demoted_but_never_zero(self) -> None:
        ledger = ProducerLedger(repeated_regression_limit=3)
        context = self._context()
        bad = producer_identity("mutate_topology", ProducerKind.MUTATION_OPERATOR)
        for _ in range(3):
            ledger.credit_rejected_proposal(bad, context, "proxy_ifeval", 0.9, 0.1)
        assert ledger.is_repeated_regressor(bad, context.key())
        weights = ledger.operator_weights(
            ("mutate_prompt", "mutate_topology"), context.key(), kind=ProducerKind.MUTATION_OPERATOR
        )
        assert 0.0 < weights["mutate_topology"] < weights["mutate_prompt"]

    def test_breeding_uses_favored_subset(self) -> None:
        store = PopulationStore()
        store.add(_genome("a"))
        store.add(_genome("b"))
        store.add(_genome("c"))
        for g in store.list_all():
            g.fitness_score = 1.0
            store.add(g)
        cycle = EvolutionCycle()
        island_pop = _single_island(store)
        config = EvolutionConfig(
            favor_productive_operators=True,
            mutation_operators_per_child=2,
            population_size=6,
        )
        random.seed(11)
        cycle._breed_island(island_pop, 0, store, config, cap=5)
        children = [
            g
            for g in store.list_all()
            if g.origin is not None and g.origin.producer.name == "mutate_selected"
        ]
        assert children, "favored breeding must produce mutate_selected children"
        for child in children:
            # crossover_and_mutate's note shape: "crossover then mutate_selected (op, op)"
            applied = child.origin.note.split("(", 1)[1].rstrip(")").split(", ")
            assert 1 <= len(applied) <= 2
            assert set(applied) <= set(MUTATION_OPERATOR_NAMES)

    def test_breeding_default_applies_all_operators(self) -> None:
        store = PopulationStore()
        store.add(_genome("a"))
        store.add(_genome("b"))
        for g in store.list_all():
            g.fitness_score = 1.0
            store.add(g)
        cycle = EvolutionCycle()
        island_pop = _single_island(store)
        config = EvolutionConfig(population_size=4)
        cycle._breed_island(island_pop, 0, store, config, cap=3)
        children = [g for g in store.list_all() if g.name.endswith("-all-mut")]
        assert children
        assert all(
            g.origin is not None and g.origin.producer.name == "mutate_all" for g in children
        )

    def _credit_verified_outcome(self, outcome, accepted: bool) -> None:
        cycle = EvolutionCycle()
        config = EvolutionConfig(target_benchmarks=["proxy_ifeval"])
        cycle._credit_verified_outcome(
            outcome, config, producer_name="reflective_improve", kind=ProducerKind.PROMPT_OPERATOR
        )


def _single_island(store: PopulationStore):
    from maistro_evolve.population import IslandPopulation

    ip = IslandPopulation(1)
    for g in store.list_all():
        ip.assign(g)
    return ip


# --------------------------------------------------------------------------
# AC4: negative credit retained for repeated regressions/failures
# --------------------------------------------------------------------------


class TestNegativeCredit:
    def _context(self) -> EvalContext:
        return EvalContext.from_harness(EvalHarness(), ["proxy_ifeval"])

    def test_regression_counters_never_decay(self) -> None:
        ledger = ProducerLedger(repeated_regression_limit=2)
        context = self._context()
        producer = producer_identity("mutate_node", ProducerKind.MUTATION_OPERATOR)
        child = mutate_node(_genome(), 1.0)
        ledger.register_candidate(child)
        ledger.credit(child, "proxy_ifeval", 0.2, context=context)  # regression
        ledger.credit(child, "proxy_ifeval", 0.3, context=context)  # regression
        assert ledger.is_repeated_regressor(producer, context.key())
        # Later neutral/improvement events never erase the retained negatives.
        ledger.credit(child, "proxy_ifeval", 0.5, context=context)  # neutral
        ledger.credit(child, "proxy_ifeval", 0.9, context=context)  # improvement
        ledger.credit(child, "proxy_ifeval", 0.95, context=context)  # improvement
        stats = ledger.stats(producer, context.key())
        assert stats is not None
        assert stats.regressions == 2
        assert stats.improvements == 2
        assert stats.total_delta == pytest.approx(-0.3 - 0.2 + 0.0 + 0.4 + 0.45)
        # Flag is rate-honest (no longer regression-majority) but the negative
        # credit history is fully retained in stats and the event log.
        assert not ledger.is_repeated_regressor(producer, context.key())
        outcomes = [e.outcome for e in ledger.events]
        assert outcomes.count("regression") == 2

    def test_rejected_proposals_retain_negative_credit(self) -> None:
        ledger = ProducerLedger(repeated_regression_limit=2)
        context = self._context()
        producer = producer_identity("hyper_mutator", ProducerKind.SEARCH_OPERATOR)
        for _ in range(3):
            ledger.credit_rejected_proposal(producer, context, "proxy_ifeval", 0.8, 0.2)
        stats = ledger.stats(producer, context.key())
        assert stats is not None
        assert stats.regressions == 3 and stats.improvements == 0
        assert ledger.is_repeated_regressor(producer, context.key())
        assert all(e.candidate_id == "" for e in ledger.events)
        # The audit report surfaces the retained flag beside the counters.
        row = ledger.attribution_report(context.key())["producers"][0]
        assert row["repeated_regressor"] is True
        assert row["regressions"] == 3 and row["neutral"] == 0

    def test_stub_failures_counted_without_diluting_success_rate(self) -> None:
        ledger = ProducerLedger()
        context = self._context()
        producer = producer_identity("mutate_prompt", ProducerKind.MUTATION_OPERATOR)
        child = mutate_prompt(_genome(), 1.0)
        ledger.register_candidate(child)
        ledger.credit(child, "proxy_ifeval", 0.9, context=context)
        ledger.credit(child, "proxy_ifeval", 0.0, context=context, stub=True)
        ledger.credit(child, "proxy_ifeval", 0.0, context=context, stub=True)
        stats = ledger.stats(producer, context.key())
        assert stats is not None
        assert stats.failures == 2
        # Stubs are noise (SPEC-202): recorded, but not counted as attempts.
        assert stats.attempts == 1
        assert stats.success_rate == 1.0

    def test_config_rejects_invalid_ledger_knobs(self) -> None:
        with pytest.raises(ValueError):
            ProducerLedger(repeated_regression_limit=0)
        with pytest.raises(ValueError):
            ProducerLedger(exploration_floor=1.5)


# --------------------------------------------------------------------------
# AC5: attribution is auditable and scoped to comparable evaluation contexts
# --------------------------------------------------------------------------


class TestAuditAndScoping:
    def test_credit_scoped_by_evaluation_context(self) -> None:
        ledger = ProducerLedger()
        producer = producer_identity("mutate_prompt", ProducerKind.MUTATION_OPERATOR)
        proxy = EvalContext.from_harness(EvalHarness(), ["proxy_ifeval"])
        real = EvalContext(fidelity="real", benchmarks=("ifeval",))
        child = mutate_prompt(_genome(), 1.0)
        ledger.register_candidate(child)
        ledger.credit(child, "proxy_ifeval", 0.9, context=proxy)
        # Same benchmark, different harness fidelity: a distinct comparable scope.
        ledger.credit(child, "proxy_ifeval", 0.1, context=real)
        proxy_stats = ledger.stats(producer, proxy.key())
        real_stats = ledger.stats(producer, real.key())
        assert proxy_stats is not None and real_stats is not None
        assert proxy_stats.improvements == 1 and real_stats.regressions == 1
        # Distinct buckets — a proxy fluke never floats the real-context stats.
        assert proxy_stats != real_stats
        assert len(ledger.all_stats()) == 2

    def test_attribution_report_is_audit_log(self) -> None:
        ledger = ProducerLedger()
        child = mutate_prompt(_genome(), 1.0)
        ledger.register_candidate(child)
        proxy = EvalContext.from_harness(EvalHarness(), ["proxy_ifeval"])
        real = EvalContext(fidelity="real", benchmarks=("proxy_ifeval",))
        ledger.credit(child, "proxy_ifeval", 0.9, context=proxy)
        ledger.credit(child, "proxy_ifeval", 0.1, context=real)
        report = ledger.attribution_report()
        assert report["schema"] == ATTRIBUTION_SCHEMA_VERSION
        assert len(report["events"]) == 2
        assert [e["sequence"] for e in report["events"]] == [1, 2]
        assert report["events"][0]["producer"]["name"] == "mutate_prompt"
        assert report["events"][0]["producer"]["version"] == PRODUCER_VERSIONS["mutate_prompt"]
        assert report["events"][0]["context_key"] == proxy.key()
        # Folded per-producer view beside the raw log, carrying the retained-
        # negative-credit flag (AC4) so one dump answers both audit questions.
        assert len(report["producers"]) == 2
        by_context = {row["context"]: row for row in report["producers"]}
        assert by_context[proxy.key()]["improvements"] == 1
        assert by_context[real.key()]["regressions"] == 1
        assert all(row["repeated_regressor"] is False for row in report["producers"])
        # Scoped report: only the requested comparable context, in both views.
        scoped = ledger.attribution_report(context_key=real.key())
        assert len(scoped["events"]) == 1
        assert scoped["events"][0]["outcome"] == "regression"
        assert [row["context"] for row in scoped["producers"]] == [real.key()]

    def test_eval_context_key_is_scope_sensitive(self) -> None:
        a = EvalContext(fidelity="proxy", benchmarks=("b", "a"), scope="")
        b = EvalContext(fidelity="proxy", benchmarks=("a", "b"), scope="")
        c = EvalContext(fidelity="proxy", benchmarks=("a", "b"), scope="run-2")
        # Benchmark order normalized; scope partitions otherwise-comparable runs.
        assert a.key() == b.key()
        assert a.key() != c.key()

    def test_from_harness_reads_fidelity(self) -> None:
        context = EvalContext.from_harness(EvalHarness(benchmark_fidelity="real"), ["bfcl"])
        assert context.fidelity == "real"
        assert context.benchmarks == ("bfcl",)

    def test_credit_verified_outcome_helper_paths(self) -> None:
        from types import SimpleNamespace

        cycle = EvolutionCycle()
        config = EvolutionConfig(target_benchmarks=["proxy_ifeval"])
        accepted = SimpleNamespace(
            accepted=True,
            challenger=spawn_challenger(_genome(), "q1", "improved prompt."),
            best_candidate_score=0.9,
            challenger_id="whatever",
            baseline_score=0.5,
            benchmark="proxy_ifeval",
        )
        cycle._credit_verified_outcome(
            accepted,
            config,
            producer_name="reflective_improve",
            kind=ProducerKind.PROMPT_OPERATOR,
        )
        assert len(cycle.ledger.events) == 1
        assert cycle.ledger.events[0].accepted is True
        rejected = SimpleNamespace(
            accepted=False,
            challenger=None,
            best_candidate_score=0.3,
            challenger_id=None,
            baseline_score=0.5,
            benchmark="proxy_ifeval",
        )
        cycle._credit_verified_outcome(
            rejected,
            config,
            producer_name="reflective_improve",
            kind=ProducerKind.PROMPT_OPERATOR,
        )
        assert len(cycle.ledger.events) == 2
        assert cycle.ledger.events[1].outcome == "regression"
        producer = producer_identity("reflective_improve", ProducerKind.PROMPT_OPERATOR)
        stats = cycle.ledger.stats(producer, cycle._eval_context(config).key())
        assert stats is not None
        assert (stats.improvements, stats.regressions) == (1, 1)

    def test_identity_is_frozen(self) -> None:
        from pydantic import ValidationError

        identity = ProducerIdentity(kind=ProducerKind.GENERATOR, name="seed")
        with pytest.raises(ValidationError):
            identity.name = "other"  # type: ignore[misc]
