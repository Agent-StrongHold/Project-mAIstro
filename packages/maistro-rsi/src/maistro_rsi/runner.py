"""RSI cycle orchestration: branch on the agent's own codebase inside an
isolated sandbox, score baseline vs. candidate against the shared benchmark
suite, and let the existing Elo tournament decide whether the self-modification
actually won.

Deliberately thin — it composes pieces that already exist (or are scaffolded
alongside it) rather than reimplementing them:

- `maistro_rsi.sandbox`         → isolated execution (protocol-first; Docker today)
- `maistro_rsi.selfbranch`      → clone/branch/patch/test/PR via `maistro.tools.git`
- `maistro_rsi.quota_burn`      → pick the model with the most idle headroom
- `maistro_evolve.harness`      → run the (8 + RSI-added) benchmark suite
- `maistro_evolve.tournament`   → Elo battle: did the candidate beat the baseline?
"""

from __future__ import annotations

import shutil
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path as _Path

import structlog

from maistro_evolve.harness import BenchmarkFidelity, EvalHarness
from maistro_evolve.tournament import EloTournament, GenomeBattle
from maistro_evolve.types import EvalResult, PipelineGenome
from maistro_rsi.benchmarks import RSI_BENCHMARKS
from maistro_rsi.gateway import LlmCall, make_gateway_llm_call
from maistro_rsi.protocols import ApplyPatchFn, MicroVmSandbox, WorkspaceProbeFn
from maistro_rsi.quota_burn import QuotaBurnScheduler
from maistro_rsi.sandbox.microvm import create_rsi_sandbox
from maistro_rsi.selfbranch import (
    QuarantineCheckFn,
    SelfBranchResult,
    new_attempt,
    run_self_branch_attempt,
)

logger = structlog.get_logger()

DEFAULT_BENCHMARKS = ["proxy_swebench", "proxy_swebench_pro", "proxy_terminalbench"]

# Not a hardcoded /tmp literal (bandit B108): resolved via tempfile.gettempdir()
# so it honors $TMPDIR / the platform temp dir instead of assuming /tmp exists
# and is safe to write into. Each cycle still creates a unique per-run_id
# subdirectory beneath this root (see RsiCycle.run), so concurrent runs never
# collide even though the root itself is shared.
DEFAULT_WORKSPACE_ROOT = str(_Path(tempfile.gettempdir()) / "maistro-workspace" / "rsi")

_PROBE_TIMEOUT_S = 300


def _parse_probe_score(exit_code: int, output: str) -> float:
    """Score a probe command: last output line as a float when it parses,
    else 1.0/0.0 from the exit code."""
    lines = [line.strip() for line in output.strip().splitlines() if line.strip()]
    if lines:
        try:
            return float(lines[-1])
        except ValueError:
            pass
    return 1.0 if exit_code == 0 else 0.0


def probe_from_commands(
    commands: dict[str, str], *, timeout: int = _PROBE_TIMEOUT_S
) -> WorkspaceProbeFn:
    """Build a workspace probe that runs each named shell command in the
    checkout and scores it via :func:`_parse_probe_score`."""

    async def _probe(sandbox: MicroVmSandbox, workspace: str) -> dict[str, float]:
        scores: dict[str, float] = {}
        for name, command in commands.items():
            exit_code, output = await sandbox.exec(command, timeout=timeout)
            scores[name] = _parse_probe_score(exit_code, output)
        return scores

    return _probe


@dataclass
class RsiCycleConfig:
    repo_url: str
    test_command: str
    workspace_root: str = DEFAULT_WORKSPACE_ROOT
    benchmarks: list[str] = field(default_factory=lambda: list(DEFAULT_BENCHMARKS))
    open_prs: bool = False
    base_branch: str = "main"
    # Keep the cloned workspace after the cycle (debugging). Default False:
    # long-running loops would otherwise slowly fill the disk with one clone
    # per run_id that nothing ever deletes.
    keep_workspace: bool = False
    # Differential workspace benchmarks: name → shell command run in the
    # workspace before and after the patch. Score = the command's last output
    # line parsed as a float, else 1.0/0.0 from its exit code. When set, these
    # measured battles replace the stock genome benchmarks — the tournament
    # then scores what the patch actually did to the checkout.
    benchmark_commands: dict[str, str] = field(default_factory=dict)


@dataclass
class RsiCycleResult:
    run_id: str
    model_used: str | None
    branch_result: SelfBranchResult
    baseline_results: list[EvalResult]
    candidate_results: list[EvalResult]
    battles: list[GenomeBattle]

    @property
    def benchmarks_won(self) -> int:
        return sum(1 for b in self.battles if b.winner_id == b.genome_b_id)

    @property
    def improved(self) -> bool:
        return self.branch_result.tests_passed and self.benchmarks_won > len(self.battles) / 2


def build_harness(benchmark_fidelity: BenchmarkFidelity = "proxy") -> EvalHarness:
    """An `EvalHarness` carrying maistro-evolve's stock benchmarks plus the
    longer-horizon ones added here (e.g. SWE-Bench Pro).

    ``RSI_BENCHMARKS`` are all proxy-tier, so at ``benchmark_fidelity="real"``
    they are **omitted**, not registered. Adding them would leave a harness that
    reports ``fidelity == "real"`` while returning handcrafted-sample scores —
    and RSI results feed promotion evidence, which is the worst place for a
    proxy number wearing a real label. ``EvalHarness.register_benchmark`` also
    rejects this independently; the explicit skip here is so the caller gets a
    working real harness instead of an exception.
    """
    harness = EvalHarness(benchmark_fidelity=benchmark_fidelity)
    if benchmark_fidelity == "real":
        logger.info(
            "rsi_benchmarks_omitted_at_real_fidelity",
            omitted=sorted(RSI_BENCHMARKS),
            reason="proxy-tier runners cannot be registered on a real harness",
        )
        return harness
    for name, runner in RSI_BENCHMARKS.items():
        harness.register_benchmark(name, runner)
    return harness


class RsiCycle:
    """One end-to-end loop: branch → patch → test → evaluate → battle."""

    def __init__(
        self,
        config: RsiCycleConfig,
        harness: EvalHarness,
        tournament: EloTournament,
        scheduler: QuotaBurnScheduler,
        apply_patch: ApplyPatchFn,
        llm_call: LlmCall | None = None,
        quarantine_check: QuarantineCheckFn | None = None,
    ) -> None:
        self._config = config
        self._harness = harness
        self._tournament = tournament
        self._scheduler = scheduler
        self._apply_patch = apply_patch
        # When None, run() builds a gateway-backed llm_call from the
        # scheduler-chosen model so benchmark scoring is real, not heuristic.
        self._llm_call = llm_call
        # Without a quarantine_check, run_self_branch_attempt refuses to ship:
        # no verdict means DENY, so a driver that opens PRs must wire one — the
        # type default is fail-closed rather than a comment asking nicely.
        self._quarantine_check = quarantine_check

    async def run(
        self,
        baseline: PipelineGenome,
        candidate: PipelineGenome,
        available_models: list[str],
    ) -> RsiCycleResult:
        run_id = uuid.uuid4().hex[:10]
        workspace = f"{self._config.workspace_root}/{run_id}"
        model = await self._scheduler.next_model(available_models)

        # Real benchmark scoring needs an llm_call. Prefer an injected one
        # (tests); otherwise build a gateway-backed call routed to the
        # scheduler-chosen model — which also makes that choice (idle-quota
        # headroom) actually drive the eval instead of being decorative. If no
        # model is available, leave it None and the benchmarks score
        # heuristically (loudly non-real).
        llm_call = self._llm_call
        if llm_call is None and model:
            llm_call = make_gateway_llm_call(model)

        sandbox = await create_rsi_sandbox(workspace)
        try:
            attempt = new_attempt(
                self._config.repo_url,
                self._config.test_command,
                base_branch=self._config.base_branch,
            )
            probe = (
                probe_from_commands(self._config.benchmark_commands)
                if self._config.benchmark_commands
                else None
            )
            branch_result = await run_self_branch_attempt(
                sandbox,
                workspace,
                attempt,
                self._apply_patch,
                open_pr=self._config.open_prs,
                quarantine_check=self._quarantine_check,
                model=model,
                probe=probe,
            )

            baseline_results, candidate_results = await self._score(
                branch_result, baseline, candidate, llm_call
            )

            battles = [
                self._tournament.record_battle(
                    benchmark=b_res.benchmark,
                    genome_a_id=baseline.id,
                    genome_b_id=candidate.id,
                    score_a=b_res.score,
                    score_b=c_res.score,
                )
                for b_res, c_res in zip(baseline_results, candidate_results, strict=False)
                if b_res.benchmark == c_res.benchmark
            ]
        finally:
            await sandbox.destroy()
            if not self._config.keep_workspace:
                shutil.rmtree(workspace, ignore_errors=True)

        # Close the quota-burn feedback loop: without recording usage, the
        # scheduler ranks against a tracker nothing writes to and keeps picking
        # the same model. Gateway-built llm_calls expose cumulative counters.
        usage_in = int(getattr(llm_call, "usage_input", 0) or 0)
        usage_out = int(getattr(llm_call, "usage_output", 0) or 0)
        if model and (usage_in or usage_out):
            await self._scheduler.record_attempt(model, usage_in, usage_out)

        result = RsiCycleResult(
            run_id=run_id,
            model_used=model,
            branch_result=branch_result,
            baseline_results=baseline_results,
            candidate_results=candidate_results,
            battles=battles,
        )

        await logger.ainfo(
            "rsi_cycle_complete",
            run_id=run_id,
            model=model,
            tests_passed=branch_result.tests_passed,
            benchmarks_won=result.benchmarks_won,
            benchmarks_total=len(battles),
            improved=result.improved,
            opened_pr=branch_result.pr_url is not None,
        )

        return result

    async def _score(
        self,
        branch_result: SelfBranchResult,
        baseline: PipelineGenome,
        candidate: PipelineGenome,
        llm_call: LlmCall | None,
    ) -> tuple[list[EvalResult], list[EvalResult]]:
        """Produce the (baseline, candidate) results the tournament battles over.

        Preference order: the *differential workspace metrics* captured around
        the patch (real evidence of what the change did to the checkout), and
        only when no probes were configured, the stock genome benchmark suite —
        which never sees the patch and is a much weaker signal (scored via
        ``llm_call`` when one is available, so it's real rather than heuristic).
        """
        base_metrics = branch_result.baseline_metrics
        cand_metrics = branch_result.candidate_metrics
        if base_metrics is not None and cand_metrics is not None:
            shared = [name for name in base_metrics if name in cand_metrics]
            baseline_results = [
                EvalResult(benchmark=name, score=base_metrics[name]) for name in shared
            ]
            candidate_results = [
                EvalResult(benchmark=name, score=cand_metrics[name]) for name in shared
            ]
            return baseline_results, candidate_results

        baseline_results = await self._harness.evaluate_genome(
            baseline,
            benchmarks=self._config.benchmarks,
            llm_call=llm_call,
        )
        candidate_results = await self._harness.evaluate_genome(
            candidate,
            benchmarks=self._config.benchmarks,
            llm_call=llm_call,
        )
        return baseline_results, candidate_results
