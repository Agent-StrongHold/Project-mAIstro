from __future__ import annotations

from typing import Any

from .bfcl import run_bfcl
from .bfcl_real import BFCLUnavailableError, run_bfcl_real
from .bfcl_real import available as _bfcl_available
from .gaia import run_gaia
from .ifeval import run_ifeval
from .ifeval_real import IFEvalUnavailableError, run_ifeval_real
from .ifeval_real import available as _ifeval_available
from .osworld import run_osworld
from .ragas import run_ragas
from .swebench import run_swebench
from .tau_bench import run_tau_bench
from .terminalbench import run_terminalbench

# Small handcrafted/lite sample sets, NOT the official benchmark corpora
# despite sharing their names (SPEC-202). The scoring methodology is real —
# ifeval/gaia/bfcl/tau_bench/ragas apply the same kind of check the official
# benchmark does (rule verification, exact-match, tool-call matching), and
# swebench/terminalbench execute the candidate and verify a real outcome
# (assertion / filesystem state) — just at a much smaller, cheaper scale than
# the official dataset + harness ("real" tier, not yet implemented for any
# benchmark).
#
# osworld is deliberately NOT registered here: there is no honest way to
# score it without real desktop-VM infrastructure that does not exist in
# this repo. run_osworld raises rather than producing any score — see
# osworld.py.
PROXY_BENCHMARKS = {
    "proxy_ifeval": run_ifeval,
    "proxy_bfcl": run_bfcl,
    "proxy_swebench": run_swebench,
    "proxy_terminalbench": run_terminalbench,
    "proxy_tau_bench": run_tau_bench,
    "proxy_gaia": run_gaia,
    "proxy_ragas": run_ragas,
}

# Official dataset + official harness (SPEC-202's `real` tier). A name only
# belongs here once its score is comparable to a published one. Both current
# entries earned their place the same way: a deterministic official grader over
# response text — no container, no reference solution, no judge model — so the
# entire cost of making each real was the LLM calls (541 for IFEval; 1,000 for
# BFCL's Python-AST track). See ifeval_real.py / bfcl_real.py, and note that
# "real bfcl" means the Python-AST track only, not all of BFCL.
#
# Real benchmarks are OPTIONAL INCLUDES. Each entry pairs its runner with an
# availability probe in _REAL_PROBES, and a `real` harness registers only the
# ones whose probe passes: a laptop without the `ifeval` extra skips IFEval and
# still runs BFCL; a 32-core box with everything installed (and, later, docker
# images for SWE-bench/Terminal-Bench) runs the lot. The operator picks by
# installing, not by configuring. Two rules keep this honest:
#   * unavailable ≠ proxy — a missing real adapter is SKIPPED (recorded on
#     EvalHarness.unavailable_real), never quietly swapped for the proxy;
#   * explicitly asking for an unavailable one raises with the install hint,
#     because an explicit ask deserves an explicit answer.
REAL_BENCHMARKS = {
    "ifeval": run_ifeval_real,
    "bfcl": run_bfcl_real,
}

# Availability probes, () -> (ok, reason). Import-cheap by construction: a probe
# must never download, never prompt, and never take longer than a file stat and
# an import attempt.
_REAL_PROBES = {
    "ifeval": _ifeval_available,
    "bfcl": _bfcl_available,
}


def available_real_benchmarks() -> tuple[dict[str, Any], dict[str, str]]:
    """Split the real registry into (runnable now, unavailable with reasons).

    The second dict maps benchmark name -> human-actionable reason ("install
    the ifeval extra", "run scripts/vendor_bfcl.py", ...). Callers surface it;
    nothing in this package acts on it silently.
    """
    runners: dict[str, Any] = {}
    unavailable: dict[str, str] = {}
    for name, runner in REAL_BENCHMARKS.items():
        ok, reason = _REAL_PROBES[name]()
        if ok:
            runners[name] = runner
        else:
            unavailable[name] = reason
    return runners, unavailable


__all__ = [
    "PROXY_BENCHMARKS",
    "REAL_BENCHMARKS",
    "BFCLUnavailableError",
    "IFEvalUnavailableError",
    "available_real_benchmarks",
    "run_osworld",
]
