from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest


@pytest.fixture(autouse=True)
def _stable_real_benchmark_availability(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Keep harness unit tests independent of checkout/package corpus layout.

    The harness contract is tested by controlling adapter availability explicitly.
    Whether the vendored BFCL corpus is present is an integration/packaging concern,
    not something that should make these unit tests environment-dependent.

    The unavailable map must name *every* real adapter the registry holds —
    including the ARC-AGI second-domain adapter (#104 M4-G), whose corpus is
    not vendored in this repository — because the harness contract test
    asserts that the available and unavailable sets together cover the real
    registry exactly. An adapter that exists but is named nowhere would be
    invisible to that assertion.

    Individual tests remain free to replace ``available_real_benchmarks`` again to
    exercise unavailable/empty combinations.
    """
    if request.node.fspath.basename != "test_harness.py":
        yield
        return

    import maistro_evolve.benchmarks as bench_pkg
    from maistro_evolve.types import EvalResult, PipelineGenome

    async def fake_bfcl(genome: PipelineGenome, llm_call: Any) -> EvalResult:
        return EvalResult(
            benchmark="bfcl",
            score=1.0,
            cost_usd=0.0,
            duration_seconds=0.0,
            samples_evaluated=1,
            metadata={"fidelity": "real"},
        )

    monkeypatch.setattr(
        bench_pkg,
        "available_real_benchmarks",
        lambda: (
            {"bfcl": fake_bfcl},
            {
                "ifeval": "optional test dependency unavailable",
                "arc_agi": "ARC-AGI corpus not vendored in this checkout",
            },
        ),
    )
    yield
