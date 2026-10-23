#!/usr/bin/env python3
"""Benchmark: M4-I adaptive escalation/routing vs fixed-routing baselines.

Issue #106's comparison exit evidence — "quality-triggered escalation and
text/image selection are compared with a fixed-routing baseline on the same
workload; record task success, cost, latency and failure cases" — recorded
as ``docs/benchmarks/m4i-adaptive-vs-fixed-baseline.json``.

The harness lives in
``packages/maistro-core/tests/graph/verification/test_adaptive_vs_fixed_baseline.py``
(the behavioral assertions run there); this script only renders its record so
the checked-in JSON is regenerable:

    uv run python scripts/bench_m4i_adaptive_vs_fixed.py \
        --output docs/benchmarks/m4i-adaptive-vs-fixed-baseline.json

Deterministic and offline: the same workload, stub gateway, and registry
metadata always produce these numbers. The execution path is production —
the real ``llm.summarize`` node, the governed Binding -> Invocation egress,
and the durable executor's supervision fold — with only the far side of the
wire stubbed. Costs come from the production ``compute_cost_cents``; latency
is the registry's per-model ``latency_p50_ms`` summed over physical requests
(modeled, not wall-clock).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
_HARNESS_PATH = (
    _REPO_ROOT
    / "packages"
    / "maistro-core"
    / "tests"
    / "graph"
    / "verification"
    / "test_adaptive_vs_fixed_baseline.py"
)


def _load_harness() -> Any:
    spec = importlib.util.spec_from_file_location("m4i_baseline_harness", _HARNESS_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load harness from {_HARNESS_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def build_report(harness: Any) -> dict[str, Any]:
    results = _run(harness)

    def task_rows(arm: Any) -> list[dict[str, Any]]:
        return [
            {
                "task": outcome.task,
                "run_status": outcome.run_status.value,
                "quality": outcome.quality,
                "success": outcome.success,
                "failure_case": outcome.failure_case,
                "requests": [
                    {
                        "model": req.model,
                        "prompt_tokens": req.prompt_tokens,
                        "completion_tokens": req.completion_tokens,
                        "image_part": req.had_image_part,
                    }
                    for req in outcome.requests
                ],
                "node_runs": outcome.node_runs,
                "cost_cents": round(outcome.cost_cents, 4),
                "latency_ms": outcome.latency_ms,
            }
            for outcome in arm.tasks.values()
        ]

    return {
        "_comment": (
            "Recorded results of scripts/bench_m4i_adaptive_vs_fixed.py (issue #106, epic M4-I), "
            "regenerate with `uv run python scripts/bench_m4i_adaptive_vs_fixed.py --output "
            "docs/benchmarks/m4i-adaptive-vs-fixed-baseline.json` (git history holds the exact "
            "landing commit). Deterministic and offline: identical workload, stub gateway, and "
            "registry metadata reproduce these numbers exactly. The execution path is production "
            "(real llm.summarize node, governed egress, durable executor supervision); only the "
            "far side of the wire is a deterministic model-dependent stub, and latency is the "
            "registry's per-model p50 summed over physical requests (modeled, not wall-clock). "
            "The behavioral assertions live in the harness test module named under 'seam'."
        ),
        "benchmark": "m4i-adaptive-vs-fixed-routing",
        "issue": "106",
        "epic": "M4-I",
        "quality_bar": harness.QUALITY_BAR,
        "seam": {
            "node": "maistro.graph.nodes.llm_summarize.LlmSummarizeNode (shipped, unmodified)",
            "egress": "governed Binding -> Invocation model.chat egress (shipped, unmodified)",
            "executor": "maistro.graph.durable_runs run_durable_graph + authoritative fold (shipped, unmodified)",
            "gateway": "deterministic model-dependent stub at the httpx wire",
            "cost": "maistro.providers.types.compute_cost_cents over registry metadata",
            "latency": "registry latency_p50_ms summed per physical request (modeled, not wall-clock)",
            "harness": str(_HARNESS_PATH.relative_to(_REPO_ROOT)),
        },
        "registry": {
            name: {
                "cost_per_1k_input_cents": meta.cost_per_1k_input,
                "cost_per_1k_output_cents": meta.cost_per_1k_output,
                "latency_p50_ms": meta.latency_p50_ms,
            }
            for name, meta in harness._MODEL_META.items()
        },
        "workload": [
            {"task": work["task"], "shape": work["task"].split("-", 1)[0]}
            for work in harness.WORKLOAD
        ],
        "arms": {arm: dict(config) for arm, config in harness._arm_configs().items()},
        "results": [
            {
                "arm": result.arm,
                "tasks_succeeded": f"{len(result.successes)}/{len(result.tasks)}",
                "successes": sorted(result.successes),
                "failure_cases": dict(sorted(result.failures.items())),
                "cost_cents": round(result.cost_cents, 4),
                "latency_ms": result.latency_ms,
                "per_task": task_rows(result),
            }
            for result in results.values()
        ],
        "recorded_table": harness.render_markdown_table(results),
    }


def _run(harness: Any) -> Any:
    import asyncio

    return asyncio.run(harness.run_comparison())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--output",
        default="",
        help="path to write the JSON record to (default: stdout only)",
    )
    args = parser.parse_args(argv)

    harness = _load_harness()
    report = build_report(harness)
    payload = json.dumps(report, indent=2, sort_keys=False)
    if args.output:
        Path(args.output).write_text(payload + "\n")
    print(report["recorded_table"])
    if args.output:
        print(f"\nwritten: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
