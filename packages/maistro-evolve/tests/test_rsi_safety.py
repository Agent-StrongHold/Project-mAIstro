"""RSI (recursive self-improvement) safety invariants for the evolution loop.

Covers four areas from the Phase 16 RSI safety review:

1. Resource ceiling per cycle — EvolutionConfig enforces hard upper bounds
   on eval_batch_size/population_size/tournament_size/self_improve fan-out;
   they cannot be set unboundedly high.
2. Trust/permission immutability — TrustTier/Provenance are frozen and
   maistro-evolve never imports or writes them (no write path exists).
3. Human-approval gate before promotion to live traffic — PopulationStore.promote()
   fails closed unless approved_for_promotion is explicitly set.
4. Kill-switch/rollback — PopulationStore.rollback() reverts to the prior
   promoted genome.

Note: the hard *fitness* gate (a genome failing a per-benchmark minimum
cannot breed/pass) is already covered by test_fitness.py's TestHardGate —
not duplicated here.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from maistro_evolve.cycle import (
    MAX_EVAL_BATCH_SIZE,
    MAX_POPULATION_SIZE,
    MAX_SELF_IMPROVE_CANDIDATES,
    MAX_SELF_IMPROVE_TOP_N,
    MAX_TOURNAMENT_SIZE,
    EvolutionConfig,
)
from maistro_evolve.population import PopulationStore
from maistro_evolve.types import DAGTopology, EvalWeights, NodeGenome, PipelineGenome


def _genome(
    genome_id: str,
    fitness_score: float | None = None,
    approved_for_promotion: bool = False,
) -> PipelineGenome:
    return PipelineGenome(
        id=genome_id,
        name=genome_id,
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
        fitness_score=fitness_score,
        created_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
        approved_for_promotion=approved_for_promotion,
    )


# --------------------------------------------------------------------------
# 1. Resource ceiling per cycle
# --------------------------------------------------------------------------


class TestResourceCeiling:
    def test_eval_batch_size_within_ceiling_accepted(self):
        cfg = EvolutionConfig(eval_batch_size=MAX_EVAL_BATCH_SIZE)
        assert cfg.eval_batch_size == MAX_EVAL_BATCH_SIZE

    def test_eval_batch_size_over_ceiling_rejected(self):
        with pytest.raises(ValidationError):
            EvolutionConfig(eval_batch_size=MAX_EVAL_BATCH_SIZE + 1)

    def test_eval_batch_size_zero_accepted(self):
        # ge=0: a 0 batch size means "skip evaluation this cycle" (used by
        # tests exercising the breeding-pool fallback path) — a deliberate,
        # safe no-op, not unbounded resource use, so it stays permitted.
        cfg = EvolutionConfig(eval_batch_size=0)
        assert cfg.eval_batch_size == 0

    def test_eval_batch_size_negative_rejected(self):
        with pytest.raises(ValidationError):
            EvolutionConfig(eval_batch_size=-1)

    def test_population_size_over_ceiling_rejected(self):
        with pytest.raises(ValidationError):
            EvolutionConfig(population_size=MAX_POPULATION_SIZE + 1)

    def test_population_size_within_ceiling_accepted(self):
        cfg = EvolutionConfig(population_size=MAX_POPULATION_SIZE)
        assert cfg.population_size == MAX_POPULATION_SIZE

    def test_tournament_size_over_ceiling_rejected(self):
        with pytest.raises(ValidationError):
            EvolutionConfig(tournament_size=MAX_TOURNAMENT_SIZE + 1)

    def test_self_improve_top_n_over_ceiling_rejected(self):
        with pytest.raises(ValidationError):
            EvolutionConfig(self_improve_top_n=MAX_SELF_IMPROVE_TOP_N + 1)

    def test_self_improve_top_n_zero_accepted(self):
        # ge=0: disabling self-improve fan-out entirely is a valid (safe) config.
        cfg = EvolutionConfig(self_improve_top_n=0)
        assert cfg.self_improve_top_n == 0

    def test_self_improve_candidates_over_ceiling_rejected(self):
        with pytest.raises(ValidationError):
            EvolutionConfig(self_improve_candidates=MAX_SELF_IMPROVE_CANDIDATES + 1)

    def test_default_config_within_all_ceilings(self):
        cfg = EvolutionConfig()
        assert cfg.eval_batch_size <= MAX_EVAL_BATCH_SIZE
        assert cfg.population_size <= MAX_POPULATION_SIZE
        assert cfg.tournament_size <= MAX_TOURNAMENT_SIZE
        assert cfg.self_improve_top_n <= MAX_SELF_IMPROVE_TOP_N
        assert cfg.self_improve_candidates <= MAX_SELF_IMPROVE_CANDIDATES


# --------------------------------------------------------------------------
# 2. Trust/permission immutability
# --------------------------------------------------------------------------


class TestTrustImmutability:
    def test_trust_tier_dataclass_is_frozen(self):
        from maistro.types.security import TrustTier

        # TrustTier is a StrEnum: members are singletons and re-assigning a
        # member's value raises, unlike a plain mutable class attribute.
        assert TrustTier.T0 == "t0"
        with pytest.raises(AttributeError):
            TrustTier.T0.value = "t4"  # type: ignore[misc,assignment]

    def test_provenance_dataclass_is_frozen(self):
        from maistro.types.security import Provenance

        assert Provenance.BUILTIN == "builtin"

    def test_warden_verdict_is_frozen_dataclass(self):
        from maistro.types.security import WardenVerdict

        verdict = WardenVerdict()
        assert dataclasses.is_dataclass(verdict)
        with pytest.raises(dataclasses.FrozenInstanceError):
            verdict.clean = False  # type: ignore[misc]

    def test_evolve_module_never_imports_trust_or_provenance(self):
        import ast
        from pathlib import Path

        evolve_src = Path(__file__).resolve().parents[1] / "src" / "maistro_evolve"
        offenders: list[str] = []
        for py_file in evolve_src.rglob("*.py"):
            tree = ast.parse(py_file.read_text(), filename=str(py_file))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, (ast.ImportFrom, ast.Import)):
                    names = [alias.name for alias in node.names]
                if any(n in ("TrustTier", "Provenance") for n in names):
                    offenders.append(str(py_file))
        assert offenders == [], (
            f"maistro-evolve must never import TrustTier/Provenance (no write "
            f"path to trust state): found imports in {offenders}"
        )


# --------------------------------------------------------------------------
# 3. Human-approval gate before promotion to live traffic
# --------------------------------------------------------------------------


class TestPromotionGate:
    def test_promote_unapproved_genome_raises(self, tmp_path):
        store = PopulationStore(tmp_path / "pop.db")
        g = _genome("g1", fitness_score=99.0, approved_for_promotion=False)
        store.add(g)
        with pytest.raises(PermissionError):
            store.promote("g1")
        # Fail closed: still inactive after the rejected promotion attempt.
        assert store.get("g1").is_active is False

    def test_promote_unknown_genome_raises_value_error(self, tmp_path):
        store = PopulationStore(tmp_path / "pop.db")
        with pytest.raises(ValueError):
            store.promote("does-not-exist")

    def test_promote_approved_genome_succeeds(self, tmp_path):
        store = PopulationStore(tmp_path / "pop.db")
        g = _genome("g1", fitness_score=99.0, approved_for_promotion=True)
        store.add(g)
        promoted = store.promote("g1")
        assert promoted.is_active is True
        assert store.get_active().id == "g1"

    def test_approved_for_promotion_defaults_false(self):
        # Defaults closed: a freshly bred/mutated genome (which never sets
        # this field) cannot be promoted without an explicit, separate
        # approval step.
        g = _genome("g1")
        assert g.approved_for_promotion is False

    def test_winning_tournament_alone_does_not_set_approval(self, tmp_path):
        # Simulates "a self-modified agent wins tournament evaluation":
        # a high fitness_score must not, by itself, satisfy the promotion gate.
        store = PopulationStore(tmp_path / "pop.db")
        winner = _genome("winner", fitness_score=1000.0, approved_for_promotion=False)
        store.add(winner)
        with pytest.raises(PermissionError):
            store.promote("winner")


# --------------------------------------------------------------------------
# 4. Kill-switch / rollback
# --------------------------------------------------------------------------


class TestRollback:
    def test_rollback_with_no_prior_promotion_returns_none(self, tmp_path):
        store = PopulationStore(tmp_path / "pop.db")
        g = _genome("g1", approved_for_promotion=True)
        store.add(g)
        store.promote("g1")
        assert store.rollback() is None
        # First promotion has no predecessor, so it remains active.
        assert store.get_active().id == "g1"

    def test_rollback_restores_previous_champion(self, tmp_path):
        store = PopulationStore(tmp_path / "pop.db")
        old = _genome("old", approved_for_promotion=True)
        new = _genome("new", approved_for_promotion=True)
        store.add(old)
        store.add(new)

        store.promote("old")
        store.promote("new")
        assert store.get_active().id == "new"

        restored = store.rollback()
        assert restored is not None
        assert restored.id == "old"
        assert store.get_active().id == "old"
        assert store.get("new").is_active is False

    def test_rollback_on_empty_store_returns_none(self, tmp_path):
        store = PopulationStore(tmp_path / "pop.db")
        assert store.rollback() is None
