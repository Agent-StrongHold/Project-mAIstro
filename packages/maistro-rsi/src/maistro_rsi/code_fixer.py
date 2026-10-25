"""Production `fix_and_score` for Stage 3 (ADR-070126-6386).

`evolve_bridge` scores a genome by the code fix its config produces, via an
injected `fix_and_score`. This is the real one: it drives the native builders
agent with the competitor's model/temperature against a target file in a
throwaway worktree off a baseline clone, then scores the result with the RSI
`Scorecard`. So a genome's `code_rsi` score is a genuine "how good a fix does
this prompt/model/config author", which is exactly what `EvolutionCycle` breeds
toward.

Kept separate from `evolve_bridge` (which stays import-light and unit-testable)
because this pulls in the whole builders + fitness stack and needs a live gateway.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import structlog

from maistro_rsi.candidate_fitness import evaluate_candidate
from maistro_rsi.competitors import Competitor
from maistro_rsi.local_loop import (
    LocalSandbox,
    _git,
    _scouted_objective,
    _targeted_objective,
    make_builders_apply_patch,
)

logger = structlog.get_logger()


class LiveCodeFixer:
    """Runs a real agent fix for one competitor+target and scores it.

    Point it at a baseline clone already checked out on ``baseline_branch``; each
    ``fix_and_score`` call adds a throwaway worktree, runs the agent with the
    competitor's config, scores the diff, and tears the worktree down.
    """

    def __init__(
        self,
        baseline_dir: str | Path,
        test_command: str,
        *,
        coverage_source: str = ".",
        coverage_pytest_args: str = "",
        agent_turns: int = 6,
        isolation: str = "local",
        image: str = "maistro-builders:latest",
        baseline_branch: str = "rsi-baseline",
        objective: str | None = None,
        timeout: int = 900,
    ) -> None:
        self._baseline = Path(baseline_dir)
        self._test_command = test_command
        self._coverage_source = coverage_source
        self._coverage_pytest_args = coverage_pytest_args
        self._agent_turns = agent_turns
        self._isolation = isolation
        self._image = image
        self._baseline_branch = baseline_branch
        self._objective = objective
        self._timeout = timeout
        self._baseline_cov: float | None = None

    def _baseline_coverage(self) -> float | None:
        if self._baseline_cov is None:
            from maistro_evolve.coverage_gate import measure_coverage

            self._baseline_cov = measure_coverage(
                self._baseline,
                source=self._coverage_source,
                pytest_args=self._coverage_pytest_args,
            )
        return self._baseline_cov

    def _objective_for(self, target: str) -> str:
        if self._objective:
            return _scouted_objective(target, self._objective)
        return _targeted_objective(target)

    async def fix_and_score(self, competitor: Competitor, target: str) -> tuple[bool, float, bool]:
        """Run the agent (competitor config) on ``target`` and score the diff.

        Returns ``(gates_passed, composite, is_stub)`` — the shape
        `evolve_bridge.FixAndScore` expects. A no-op edit is a non-accepted 0.0.
        """
        tag = uuid.uuid4().hex[:8]
        branch = f"rsi/evo-{tag}"
        cdir = self._baseline.parent / f"evo-{tag}"
        _git(
            self._baseline,
            "worktree",
            "add",
            "-q",
            "-b",
            branch,
            str(cdir),
            self._baseline_branch,
        )
        try:
            apply_fn = make_builders_apply_patch(
                self._objective_for(target),
                model=competitor.model,
                temperature=competitor.temperature,
                reasoning_effort=competitor.reasoning_effort,
                system_prompt=competitor.prompt,
                max_agent_turns=self._agent_turns,
                isolation=self._isolation,
                image=self._image,
            )
            await apply_fn(LocalSandbox(cdir), str(cdir), None)
            _git(cdir, "add", "-A")
            status = _git(cdir, "status", "--porcelain")
            changed = [ln[3:].strip() for ln in status.stdout.splitlines() if ln.strip()]
            if not changed:
                return (False, 0.0, False)
            _git(cdir, "commit", "-q", "-m", f"evo fix {target}")
            scorecard = evaluate_candidate(
                cdir,
                changed,
                test_command=self._test_command,
                coverage_source=self._coverage_source,
                coverage_pytest_args=self._coverage_pytest_args,
                baseline_coverage=self._baseline_coverage(),
                baseline_ref=self._baseline_branch,
                timeout=self._timeout,
            )
            return (scorecard.accepted, scorecard.composite, False)
        except Exception as exc:
            # Never raises — mirrors _run_variant's contract in the tournament
            # loop. A gateway timeout / transient agent failure is not evidence
            # about the genome, so mark the result a STUB (no real signal): the
            # hyper-mutator refuses to verify against stubs (SPEC-202), and one
            # flaky call no longer kills an entire multi-hour evolution run
            # (a live httpx.ReadTimeout did exactly that).
            logger.warning("code_rsi_eval_errored", competitor=competitor.label, error=str(exc))
            return (False, 0.0, True)
        finally:
            _git(self._baseline, "worktree", "remove", "--force", str(cdir), check=False)
            _git(self._baseline, "branch", "-D", branch, check=False)
