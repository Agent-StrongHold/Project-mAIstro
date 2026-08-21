from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal

from .types import EvalResult, PipelineGenome

BenchmarkRunner = Callable[[PipelineGenome, Any], Awaitable[EvalResult]]

BenchmarkFidelity = Literal["proxy", "real"]
"""Per SPEC-202: ``proxy`` is a lite version of the real methodology — small
handcrafted/lite sample sets, but genuine scoring (rule verification,
exact-match, tool-call matching, real execution + assertion/state checks),
never fabricated noise; ``real`` is the official benchmark harness against
the official dataset.

``real`` is implemented for **ifeval** (``benchmarks/ifeval_real.py``: the
official 541-prompt corpus, graded by Google Research's own vendored verifier)
and **bfcl** (``benchmarks/bfcl_real.py``: the official 1,000-instance
Python-AST track, graded by the leaderboard's own vendored ``ast_checker``).
Every other name in the proxy registry remains proxy-tier. A ``real`` harness
therefore registers two benchmarks, not seven, and deliberately does not
backfill the rest — see ``EvalHarness._register_real_benchmarks``.

There is deliberately no ``stub`` tier: a benchmark either evaluates a real
model response against real criteria (``proxy``), or it does not run at all.
Random-noise placeholder scores were removed outright rather than gated,
because a fitness signal that can silently become noise is worse than no
signal — see SPEC-202 and the evolve CLAUDE.md stability statement.
"""


class EvalHarness:
    def __init__(self, benchmark_fidelity: BenchmarkFidelity = "proxy") -> None:
        self._benchmarks: dict[str, BenchmarkRunner] = {}
        # Real adapters that exist but cannot run in this environment, mapped to
        # the human-actionable reason (missing extra, missing vendored corpus,
        # later: missing docker images). Always {} for a proxy harness.
        self.unavailable_real: dict[str, str] = {}
        if benchmark_fidelity not in ("proxy", "real"):
            # Explicitly reject anything else — including the removed "stub"
            # tier — rather than silently falling through to proxy for an
            # unrecognized value.
            raise ValueError(
                f"unknown benchmark_fidelity {benchmark_fidelity!r}; "
                "valid values are 'proxy' (default) or 'real'. There is no "
                "'stub' tier — see BenchmarkFidelity's docstring."
            )
        # Set before registering: register_benchmark enforces the tier against
        # this attribute, so it has to be true of the harness from the first
        # registration onward, not merely by the time __init__ returns.
        self.fidelity: BenchmarkFidelity = benchmark_fidelity
        if benchmark_fidelity == "real":
            self._register_real_benchmarks()
        else:
            self._register_proxy_benchmarks()

    def register_benchmark(
        self,
        name: str,
        runner_fn: BenchmarkRunner,
        *,
        fidelity: BenchmarkFidelity = "proxy",
    ) -> None:
        """Add a runner, refusing any registration that would break the tier.

        ``fidelity`` declares what tier ``runner_fn`` actually is, and defaults
        to ``"proxy"`` because that is what a custom runner almost always is —
        a caller with a genuine official-harness adapter has to say so.

        A proxy runner on a real harness is rejected. Without this the
        invariant leaked through the one door left open: ``EvalHarness`` picked
        its own registrations carefully, then any caller could
        ``register_benchmark`` a proxy runner onto a real harness and the object
        would still report ``fidelity == "real"`` while returning a
        handcrafted-sample score. ``maistro_rsi.runner.build_harness`` did
        exactly that with proxy-tier ``swebench_pro``, which could have put a
        proxy number into promotion evidence labelled real.

        The reverse (a real runner on a proxy harness) is allowed: it makes the
        harness *better* than it claims, and ``EvalResult.metadata["fidelity"]``
        still tells the truth per result.
        """
        if self.fidelity == "real" and fidelity != "real":
            raise ValueError(
                f"cannot register {fidelity}-fidelity benchmark {name!r} on a "
                "real-fidelity harness: the harness would keep reporting "
                "fidelity=='real' while returning a proxy score. Either pass "
                "fidelity='real' if this runner really is an official-harness "
                "adapter, or build the harness with benchmark_fidelity='proxy'."
            )
        self._benchmarks[name] = runner_fn

    def _register_proxy_benchmarks(self) -> None:
        from .benchmarks import PROXY_BENCHMARKS

        for name, runner in PROXY_BENCHMARKS.items():
            self.register_benchmark(name, runner)

    def _register_real_benchmarks(self) -> None:
        """Register only official-dataset/official-harness adapters.

        A ``real`` harness registers a **strict subset** of a proxy harness's
        benchmarks — two, currently — and does not backfill the rest from the
        proxy registry. Mixing the tiers behind one ``fidelity`` label is the
        specific dishonesty SPEC-202's two-tier model exists to prevent: a
        caller reading ``harness.fidelity == "real"`` off a harness whose
        swebench score came from 8 handcrafted samples has been misled by the
        object it asked.

        Consequence, called out because it is easy to trip over: a real harness
        evaluates fewer benchmarks, so ``compute_fitness`` sees fewer
        ``eval_scores``. Do not compare a real-harness fitness number to a
        proxy-harness one.

        Real adapters are **optional includes**: each has an availability probe
        (deps installed, corpus vendored, later: container images present), and
        only the ones that pass are registered. The rest land in
        ``self.unavailable_real`` with an install hint — skipped, visible, and
        never replaced by their proxy namesake. A box with everything installed
        runs everything; a bare install runs whatever is stdlib-clean (BFCL
        today) and says exactly why the others sat out.
        """
        from .benchmarks import available_real_benchmarks

        runners, self.unavailable_real = available_real_benchmarks()
        if not runners:
            reasons = "; ".join(f"{n}: {r}" for n, r in self.unavailable_real.items()) or "none"
            raise ValueError(
                "benchmark_fidelity='real' requested but no real-benchmark "
                f"adapter can run in this environment ({reasons}). Install the "
                "missing pieces, or use 'proxy' (default)."
            )
        for name, runner in runners.items():
            self.register_benchmark(name, runner, fidelity="real")

    def _reject_unrunnable(self, bench_list: list[str]) -> None:
        """Raise if any requested benchmark cannot run, before any runner starts.

        Proxy tier keeps its permissive behaviour: an unknown name is skipped,
        which yields fewer results and no false ones. Real tier refuses, because
        a short result list there looks indistinguishable from a clean run over
        everything requested — and the two reasons a real name can be missing
        ("no adapter exists yet" vs "exists, not installed here") need different
        answers from the operator.
        """
        if self.fidelity != "real":
            return
        missing = [n for n in bench_list if n not in self._benchmarks]
        if not missing:
            return
        unavailable = [n for n in missing if n in self.unavailable_real]
        unimplemented = [n for n in missing if n not in self.unavailable_real]
        parts: list[str] = []
        if unavailable:
            parts.append(
                "real adapters that exist but are unavailable in this "
                "environment: "
                + "; ".join(f"{n} ({self.unavailable_real[n]})" for n in unavailable)
            )
        if unimplemented:
            runnable = ", ".join(sorted(self._benchmarks)) or "none"
            parts.append(
                f"no real-fidelity adapter for: {', '.join(unimplemented)} "
                f"(runnable at real fidelity: {runnable}; real adapters are "
                "never backfilled from the proxy registry)"
            )
        raise ValueError(
            "cannot evaluate the requested benchmarks at real fidelity — "
            + "; ".join(parts)
            + ". Nothing was evaluated, so no cost was incurred. Narrow "
            "target_benchmarks to what this environment can run, install the "
            "missing pieces, or use benchmark_fidelity='proxy'."
        )

    async def evaluate_genome(
        self,
        genome: PipelineGenome,
        benchmarks: list[str] | None = None,
        llm_call: Any = None,
    ) -> list[EvalResult]:
        bench_list = benchmarks or list(self._benchmarks.keys())
        # Validate the WHOLE list before invoking any runner. Validating lazily
        # inside the loop meant a real harness asked for
        # ["ifeval", "bfcl", "swebench", "tau_bench"] — EvolutionConfig's
        # default — would complete ~1,500 paid LLM calls for the first two and
        # only then raise on the third, folding and persisting nothing. The
        # money is gone either way; failing first at least leaves it unspent.
        self._reject_unrunnable(bench_list)
        results: list[EvalResult] = []
        for name in bench_list:
            runner = self._benchmarks.get(name)
            if runner is None:
                continue
            result = await runner(genome, llm_call)
            results.append(result)
        return results
