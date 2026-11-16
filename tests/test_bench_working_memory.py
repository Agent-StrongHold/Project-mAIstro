"""Tests for `scripts/bench_working_memory.py` (issue #301, ADR-082226-5104 §8).

The root suite is the coverage producer for `scripts/`, so the benchmark's
changed lines are scored by the diff-coverage gate — a script with zero tests
measures 0% and reds the gate. Beyond satisfying the measurement, these tests
pin the properties that make the benchmark's numbers comparable run-to-run:
the corpus generator is deterministic, the hashed embedder is deterministic
and normalised, percentiles are computed on the reported tail, and the JSON
payload `working-memory-bench.yml` publishes has a stable shape. Everything
runs offline at a deliberately small scale (no PostgreSQL, no network) so the
suite's `--timeout=30` producer budget is respected.
"""

from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "bench_working_memory.py"

spec = importlib.util.spec_from_file_location("bench_working_memory", SCRIPT)
assert spec and spec.loader
bench = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bench
spec.loader.exec_module(bench)


class TestDeterministicInputs:
    def test_corpus_is_deterministic_and_canonical(self) -> None:
        first = bench._make_records(0, 5)
        second = bench._make_records(0, 5)
        assert [r.memory_id for r in first] == [r.memory_id for r in second]
        assert [r.content for r in first] == [r.content for r in second]
        # A different Workspace index yields a different corpus: two
        # projections must not share record identities.
        assert [r.memory_id for r in bench._make_records(1, 5)] != [r.memory_id for r in first]
        # Canonical provenance is on every generated record.
        for record in first:
            assert record.run_id and record.node_run_id and record.attempt_id
            assert record.org_id and record.agent_id and record.project_id

    def test_hash_embedder_is_deterministic_and_normalised(self) -> None:
        embedder = bench.HashEmbedder(dim=16)
        vec = embedder.vector_for("postgres pgvector memory")
        again = embedder.vector_for("postgres pgvector memory")
        assert vec == again
        norm = math.sqrt(sum(v * v for v in vec))
        assert norm == 1.0 or math.isclose(norm, 1.0)
        assert len(vec) == embedder.dimension == 16
        # A different text hashes to a different direction (almost surely).
        assert embedder.vector_for("kafka traversal") != vec

    async def test_embed_and_embed_batch_count_calls(self) -> None:
        embedder = bench.HashEmbedder(dim=8)
        assert await embedder.embed("postgres") == embedder.vector_for("postgres")
        batch = await embedder.embed_batch(["postgres", "kafka"])
        assert batch == [embedder.vector_for("postgres"), embedder.vector_for("kafka")]
        assert embedder.calls == 3


class TestPercentile:
    def test_empty_input_is_zero(self) -> None:
        assert bench._percentile([], 50) == 0.0

    def test_percentile_picks_the_reported_tail(self) -> None:
        values = [10.0, 20.0, 30.0, 40.0]
        assert bench._percentile(values, 50) == 20.0
        assert bench._percentile(values, 95) == 40.0
        assert bench._percentile(values, 0) == 10.0
        # Unsorted input is ordered first; a single sample is its own p50/p95.
        assert bench._percentile([30.0, 10.0, 20.0], 50) == 20.0
        assert bench._percentile([7.0], 95) == 7.0


class TestBench:
    async def test_bench_report_is_complete_and_consistent_at_small_scale(self) -> None:
        row = await bench.bench(workspaces=2, records_per_workspace=10, queries=5)

        assert row.workspaces == 2
        assert row.records_per_workspace == 10
        assert row.total_records == 20
        # Entities and relations come from the projection's own graph build.
        # The generated corpus puts one capitalized token ("Workspace<n>")
        # in every record, so each Workspace contributes exactly one entity
        # and no cross-entity co-occurrence — the same shape the checked-in
        # baseline (docs/benchmarks/working-memory-baseline.json) records.
        assert row.total_entities == 2
        assert row.total_relations == 0
        # Hydration cost is positive and per-record arithmetic is consistent
        # (loose tolerance: both fields are rounded to 4 decimals, and at
        # millisecond hydration times the rounding is visible).
        assert row.hydration_seconds > 0
        expected_per_record = row.hydration_seconds * 1000 / row.total_records
        assert math.isclose(
            row.hydration_per_record_ms, expected_per_record, rel_tol=0.05, abs_tol=0.01
        )
        for latency in (
            row.bm25_p50_ms,
            row.bm25_p95_ms,
            row.hybrid_p50_ms,
            row.hybrid_p95_ms,
            row.traverse_p50_ms,
            row.traverse_p95_ms,
        ):
            assert latency >= 0.0
        # Percentiles do not invert: p95 is at least the median.
        assert row.bm25_p95_ms >= row.bm25_p50_ms
        assert row.hybrid_p95_ms >= row.hybrid_p50_ms
        assert row.traverse_p95_ms >= row.traverse_p50_ms
        # RAM accounting ran (Linux /proc): non-negative deltas.
        assert row.rss_delta_kb >= 0
        assert row.rss_peak_kb >= 0

    async def test_main_writes_the_published_payload_shape(
        self, tmp_path: Path, capsys: Any
    ) -> None:
        output = tmp_path / "results.json"
        argv = [
            "bench_working_memory.py",
            "--workspaces",
            "1",
            "--records-per-workspace",
            "5",
            "--queries",
            "3",
            "--output",
            str(output),
        ]
        exit_code = await _main_with_argv(argv)
        assert exit_code == 0
        payload = json.loads(output.read_text(encoding="utf-8"))
        assert payload["benchmark"] == "working-memory-projection"
        assert payload["issue"] == "301"
        assert payload["adr"] == "ADR-082226-5104"
        assert payload["records_per_workspace"] == 5
        assert payload["queries_per_point"] == 3
        assert len(payload["results"]) == 1
        assert payload["results"][0]["workspaces"] == 1
        assert payload["results"][0]["total_records"] == 5
        # The human-readable summary line went to stdout.
        assert "workspaces=" in capsys.readouterr().out

    async def test_main_without_output_flag_prints_only(self, capsys: Any) -> None:
        argv = [
            "bench_working_memory.py",
            "--workspaces",
            "1",
            "--records-per-workspace",
            "2",
            "--queries",
            "1",
        ]
        exit_code = await _main_with_argv(argv)
        assert exit_code == 0
        assert "workspaces=" in capsys.readouterr().out


async def _main_with_argv(argv: list[str]) -> int:
    """Run the script's `main()` against an explicit argv.

    `main()` reads `sys.argv` through argparse; patching it here keeps the
    test runner's own argv out of the benchmark's option parsing.
    """
    original = sys.argv
    sys.argv = argv
    try:
        return await bench.main()
    finally:
        sys.argv = original
