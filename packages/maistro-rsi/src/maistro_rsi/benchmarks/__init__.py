from __future__ import annotations

from maistro_rsi.benchmarks.swebench_pro import run_swebench_pro

# Registered into `maistro_evolve.harness.EvalHarness` via `register_benchmark`
# rather than `PROXY_BENCHMARKS`, since these are RSI-specific additions on top
# of the 8 the harness already ships with.
RSI_BENCHMARKS = {
    "proxy_swebench_pro": run_swebench_pro,
}

__all__ = ["RSI_BENCHMARKS", "run_swebench_pro"]
