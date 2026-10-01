"""Operator-surface tests for the #384 calibration + provenance wiring.

`python -m maistro_rsi calibrate` runs the real `calibrate_proxy_scorers`
harness against a stored genome (stubbed here at the harness boundary — the
harness's own suite pins its scoring behavior); `evolve` must surface the
champion's verified-evidence provenance next to its fitness. Together they
keep the #384 acceptance surfaces reachable from production code, not only
from tests: champion selection provenance is printed by `evolve`, and the
narration false-positive rate is obtainable offline without hand-written
wiring. The handler reports; it must never gate.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from maistro_evolve.promotion import (
    EVIDENCE_CYCLE_KEY,
    HISTORY_KEY,
    OBJECTIVE_VERSION_KEY,
    SAMPLES_KEY,
)
from maistro_evolve.types import DAGTopology, EvalWeights, NodeGenome, PipelineGenome
from maistro_rsi.__main__ import _build_parser, _calibrate, _print_champion_provenance
from maistro_rsi.evolve_bridge import open_population


def make_genome(
    genome_id: str = "cal-g1",
    fitness: float | None = None,
    scores: dict[str, float] | None = None,
    evidence: dict[str, str] | None = None,
) -> PipelineGenome:
    return PipelineGenome(
        id=genome_id,
        name=f"genome-{genome_id}",
        topology=DAGTopology(
            nodes=[
                NodeGenome(
                    id="q1",
                    role="queen",
                    strategy="react",
                    model="test-model",
                    temperature=0.2,
                    max_tokens=128,
                    system_prompt="test",
                    max_tool_rounds=1,
                )
            ],
            edges=[],
            entry_node="q1",
            max_cycles=1,
            beam_width=1,
            use_scout=False,
        ),
        eval_weights=EvalWeights(),
        fitness_score=fitness,
        eval_scores=scores or {},
        eval_evidence=evidence or {},
        created_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
    )


def _eligible(genome: PipelineGenome, samples: int = 2, cycle: int = 1) -> PipelineGenome:
    """Stamp a genome with selection-eligible evidence (#854): repeated
    independent samples with a stable spread, objective-stamped and current.
    Champion APIs (``get_champion``/``champion_provenance``) run the shared
    ``selection_eligibility`` contract, so fixtures that need a champion to
    exist must carry evidence that clears it — same helper shape as the
    evolve suite's ``test_champion_provenance.py::_evidence``."""
    samples_param: dict[str, int] = genome.harness_params.setdefault(SAMPLES_KEY, {})
    history_param: dict[str, list[float]] = genome.harness_params.setdefault(HISTORY_KEY, {})
    for bench, score in genome.eval_scores.items():
        samples_param[bench] = samples
        history_param[bench] = [score - 0.01] * (samples - 1) + [score + 0.01]
    genome.harness_params[OBJECTIVE_VERSION_KEY] = "objective-test"
    genome.harness_params[EVIDENCE_CYCLE_KEY] = cycle
    return genome


def _report(fpr: float) -> dict[str, Any]:
    """A calibration report shaped exactly like the harness's, for one scorer."""
    return {
        "calibration": "adversarial-narration-v1",
        "scorers": {
            "proxy_bfcl": {
                "narration_false_positive_rate": fpr,
                "narration_fixtures": 5,
                "narration_false_positives_implied": round(fpr * 5),
                "verified_positive_rate": 1.0,
                "verified_fixtures": 5,
                "verified_failures_implied": 0,
            },
        },
    }


@pytest.fixture()
def stub_harness(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Stub the calibration harness + provider at their source modules.

    `_calibrate` imports both function-level, so patching the source module
    attributes intercepts the handler's imports. The provider stub records its
    wiring without touching the real outbound-policy global or the network.
    """
    calls: dict[str, Any] = {}

    async def fake_calibrate(genome: PipelineGenome, llm_call: Any) -> dict[str, Any]:
        calls["genome_id"] = genome.id
        calls["llm_call"] = llm_call
        return calls["report"]

    class FakeProvider:
        def __init__(self, **kwargs: Any) -> None:
            calls["provider_kwargs"] = kwargs

    import maistro_evolve.benchmarks.calibration as calibration_mod
    import maistro_evolve.providers.openai_compatible as provider_mod

    monkeypatch.setattr(calibration_mod, "calibrate_proxy_scorers", fake_calibrate)
    monkeypatch.setattr(provider_mod, "OpenAICompatibleProvider", FakeProvider)
    return calls


class TestCalibrateParser:
    def test_defaults(self) -> None:
        args = _build_parser().parse_args(["calibrate"])
        assert args.command == "calibrate"
        assert args.db is None
        assert args.genome_id is None
        assert args.model is None
        assert args.base_url is None
        assert args.api_key is None
        assert args.allow_unauthenticated_provider is False
        assert args.json is False

    def test_genome_id_and_json_flags_parse(self) -> None:
        args = _build_parser().parse_args(
            ["calibrate", "--db", "p.db", "--genome-id", "g9", "--json"]
        )
        assert args.db == "p.db"
        assert args.genome_id == "g9"
        assert args.json is True


class TestCalibrateHandler:
    def test_errors_without_a_genome(self, capsys: pytest.CaptureFixture[str]) -> None:
        args = _build_parser().parse_args(["calibrate"])
        assert _calibrate(args) == 2
        assert "no genome to calibrate" in capsys.readouterr().err

    def test_names_the_genome_when_the_id_is_unknown(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        args = _build_parser().parse_args(["calibrate", "--genome-id", "missing"])
        assert _calibrate(args) == 2
        assert "id 'missing'" in capsys.readouterr().err

    def test_runs_harness_against_the_champion_and_prints_the_report(
        self,
        tmp_path: Any,
        capsys: pytest.CaptureFixture[str],
        stub_harness: dict[str, Any],
    ) -> None:
        db = str(tmp_path / "pop.db")
        store = open_population(db)
        store.add(make_genome(genome_id="weak", fitness=0.1))  # never evaluated: ineligible
        store.add(
            _eligible(
                make_genome(
                    genome_id="champ",
                    fitness=0.9,
                    scores={"proxy_bfcl": 1.0},
                    evidence={"proxy_bfcl": "structured_call"},
                )
            )
        )
        stub_harness["report"] = _report(0.0)

        args = _build_parser().parse_args(["calibrate", "--db", db, "--model", "m1"])
        assert _calibrate(args) == 0

        # The harness received the champion (highest fitness), not just any genome.
        assert stub_harness["genome_id"] == "champ"
        assert stub_harness["provider_kwargs"]["model"] == "m1"

        out = capsys.readouterr().out
        assert "narration_fpr=0.0" in out
        assert "[clean]" in out
        # Reports; it does not gate — exit 0 even alongside the reminder.
        assert "scoring authority stays with fitness.py" in out

    def test_flags_narration_leaks_in_the_human_report(
        self,
        tmp_path: Any,
        capsys: pytest.CaptureFixture[str],
        stub_harness: dict[str, Any],
    ) -> None:
        db = str(tmp_path / "pop.db")
        open_population(db).add(
            _eligible(make_genome(genome_id="g", fitness=0.5, scores={"proxy_bfcl": 0.5}))
        )
        stub_harness["report"] = _report(0.2)

        args = _build_parser().parse_args(["calibrate", "--db", db])
        assert _calibrate(args) == 0  # reporting, not gating: a leak is not an error code
        out = capsys.readouterr().out
        assert "[LEAK]" in out
        assert "narration_fpr=0.2" in out
        assert "narration_false_positives_implied" not in out  # human report, not raw JSON

    def test_json_output_is_the_machine_readable_report(
        self,
        tmp_path: Any,
        capsys: pytest.CaptureFixture[str],
        stub_harness: dict[str, Any],
    ) -> None:
        db = str(tmp_path / "pop.db")
        open_population(db).add(
            _eligible(make_genome(genome_id="g", fitness=0.5, scores={"proxy_bfcl": 0.5}))
        )
        stub_harness["report"] = _report(0.0)

        args = _build_parser().parse_args(["calibrate", "--db", db, "--json"])
        assert _calibrate(args) == 0
        out = capsys.readouterr().out
        assert json.loads(out) == _report(0.0)
        assert "clean" not in out  # no human prose mixed into the JSON

    def test_genome_id_overrides_champion_selection(
        self,
        tmp_path: Any,
        stub_harness: dict[str, Any],
    ) -> None:
        db = str(tmp_path / "pop.db")
        store = open_population(db)
        store.add(make_genome(genome_id="champ", fitness=0.9))
        store.add(make_genome(genome_id="other", fitness=0.1))
        stub_harness["report"] = _report(0.0)

        args = _build_parser().parse_args(["calibrate", "--db", db, "--genome-id", "other"])
        assert _calibrate(args) == 0
        assert stub_harness["genome_id"] == "other"


class TestChampionProvenancePrinting:
    def test_prints_verified_evidence_per_scored_benchmark(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        store = open_population(None)
        store.add(
            _eligible(
                make_genome(
                    genome_id="champ",
                    fitness=0.9,
                    scores={"proxy_bfcl": 1.0, "proxy_gaia": 0.5},
                    evidence={"proxy_bfcl": "structured_call"},
                )
            )
        )
        _print_champion_provenance(store)
        out = capsys.readouterr().out
        assert "proxy_bfcl: score=1.0 evidence=structured_call" in out
        # Absence of an evidence record is recorded as "unverified", never dropped.
        assert "proxy_gaia: score=0.5 evidence=unverified" in out

    def test_prints_nothing_without_a_scored_champion(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _print_champion_provenance(open_population(None))
        assert capsys.readouterr().out == ""
