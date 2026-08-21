from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from maistro.agents.strategies.react import ReactStrategy
from maistro.types.agent import ReasoningResult

if TYPE_CHECKING:
    from maistro.protocols.llm import LLMClient
    from maistro.protocols.tracing import Trace

logger = logging.getLogger("maistro.strategy.builders_learning")


class BuildersLearningStrategy:
    """Frank/Mason with repo recon, failure diagnosis, learning loop."""

    def __init__(
        self,
        max_rounds: int = 10,
        force_tool_first: bool = False,
        enable_learning: bool = True,
    ) -> None:
        self.max_rounds = max_rounds
        self.force_tool_first = force_tool_first
        self.enable_learning = enable_learning
        self._react = ReactStrategy(max_rounds=max_rounds, force_tool_first=force_tool_first)
        self.process = None
        self.build = None

    async def reason(
        self,
        messages: list[dict[str, Any]],
        model: str,
        llm: LLMClient,
        *,
        trace: Trace | None = None,
        warden: Any = None,
        **kwargs: Any,
    ) -> ReasoningResult:
        _ = kwargs.get("run_id")

        worker = kwargs.get("worker", "unknown")

        if worker == "frank":
            return await self._frank_with_learning(messages, model, llm, trace, warden, **kwargs)
        if worker == "mason":
            return await self._mason_with_learning(messages, model, llm, trace, warden, **kwargs)

        return await self._react.reason(messages, model, llm, trace=trace, warden=warden, **kwargs)

    async def _frank_with_learning(
        self,
        messages: list[dict[str, Any]],
        model: str,
        llm: LLMClient,
        trace: Trace | None,
        warden: Any,
        **kwargs: Any,
    ) -> ReasoningResult:
        _ = kwargs.get("run_id")

        repo_state = await self._check_repository_state(**kwargs)

        failure_patterns = await self._analyze_failure_patterns(**kwargs)

        context = {
            "existing_code": repo_state.get("code", []),
            "existing_tests": repo_state.get("tests", []),
            "similar_issues": failure_patterns.get("similar_issues", []),
            "previous_failures": failure_patterns.get("failures", []),
            "rejection_reasons": failure_patterns.get("reasons", []),
            "coverage_expectation": "85% first pass, 95% final",
        }

        result = await self._react.reason(
            messages, model, llm, trace=trace, warden=warden, context=context, **kwargs
        )

        _ = {
            "worker": "frank",
            "run_id": kwargs.get("run_id"),
            "repository_state": repo_state,
            "failure_patterns": failure_patterns,
            "expectation": "First implementation - expect 85% coverage",
            "timestamp": self._utc_now(),
        }
        logger.info("Frank diagnostic produced")

        if self.enable_learning:
            await self._store_frank_learning(repo_state, failure_patterns, result)

        return result

    async def _mason_with_learning(
        self,
        messages: list[dict[str, Any]],
        model: str,
        llm: LLMClient,
        trace: Trace | None,
        warden: Any,
        **kwargs: Any,
    ) -> ReasoningResult:
        _ = kwargs.get("run_id")

        frank_diagnostic = kwargs.get("frank_diagnostic", {})

        execution_mode = "fix" if frank_diagnostic.get("existing_code") else "implement"

        context = {
            "frank_diagnostic": frank_diagnostic,
            "execution_mode": execution_mode,
            "coverage_expectation": "85% first pass, 95% final",
            "diagnostic_checks": [
                "coverage",
                "type_errors",
                "lint_errors",
                "security_issues",
                "docstrings",
                "error_handling",
                "naming_conventions",
                "architecture_violations",
            ],
        }

        result = await self._react.reason(
            messages, model, llm, trace=trace, warden=warden, context=context, **kwargs
        )

        diagnostics = await self._run_pr_diagnostics(**kwargs)

        if diagnostics.get("has_critical_issues"):
            logger.warning(f"PR would be rejected: {diagnostics.get('issues')}")
            result = ReasoningResult(
                response=(
                    f"{result.response}\n\n"
                    "Self-diagnosis: Found "
                    f"{len(diagnostics.get('issues', []))} "
                    "issues - must fix before PR"
                ),
                done=False,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                tool_history=result.tool_history,
            )
        else:
            if self.enable_learning:
                await self._store_mason_learning(diagnostics, result)

        return result

    async def _check_repository_state(
        self,
        **kwargs: Any,
    ) -> dict[str, Any]:
        tool_executor = kwargs.get("tool_executor")
        if not tool_executor:
            logger.warning("No tool_executor -- skipping repo recon")
            return {"code": [], "tests": [], "failed_prs": []}

        logger.info("Running repository reconnaissance")
        try:
            code = await tool_executor(
                "shell", {"command": "find src/maistro -name '*.py' -type f | head -50"}
            )
            tests = await tool_executor(
                "shell", {"command": "find tests -name '*.py' -type f | head -50"}
            )
            return {
                "code": str(code).strip().split("\n") if code else [],
                "tests": str(tests).strip().split("\n") if tests else [],
                "failed_prs": [],
            }
        except Exception:
            logger.debug("Repo recon failed", exc_info=True)
            return {"code": [], "tests": [], "failed_prs": []}

    async def _analyze_failure_patterns(
        self,
        **kwargs: Any,
    ) -> dict[str, Any]:
        tool_executor = kwargs.get("tool_executor")
        if not tool_executor:
            return {"similar_issues": [], "failures": [], "reasons": [], "lessons": []}

        logger.info("Analyzing failure patterns")
        try:
            result = await tool_executor(
                "github",
                {
                    "action": "search_issues",
                    "query": "is:pr is:closed label:rejected",
                },
            )
            return {
                "similar_issues": [],
                "failures": str(result).strip().split("\n")[:10] if result else [],
                "reasons": [],
                "lessons": [],
            }
        except Exception:
            logger.debug("Failure analysis skipped", exc_info=True)
            return {"similar_issues": [], "failures": [], "reasons": [], "lessons": []}

    async def _run_pr_diagnostics(
        self,
        **kwargs: Any,
    ) -> dict[str, Any]:
        tool_executor = kwargs.get("tool_executor")
        if not tool_executor:
            return {"all_passed": True, "issues": [], "has_critical_issues": False}

        logger.info("Running PR diagnostics (quality gates)")
        issues: list[str] = []
        try:
            ruff = await tool_executor(
                "shell", {"command": "ruff check src/maistro/ 2>&1 | tail -3"}
            )
            if ruff and "error" in str(ruff).lower():
                issues.append(f"ruff: {str(ruff)[:200]}")
        except Exception as e:
            issues.append(f"ruff: tool_executor failed: {e}")
        try:
            mypy = await tool_executor(
                "shell", {"command": "mypy src/maistro/ --strict 2>&1 | tail -3"}
            )
            if mypy and "error" in str(mypy).lower():
                issues.append(f"mypy: {str(mypy)[:200]}")
        except Exception as e:
            issues.append(f"mypy: tool_executor failed: {e}")
        try:
            tests = await tool_executor(
                "shell", {"command": "pytest tests/ -x -q --tb=line 2>&1 | tail -5"}
            )
            if tests and "failed" in str(tests).lower():
                issues.append(f"pytest: {str(tests)[:200]}")
        except Exception as e:
            issues.append(f"pytest: tool_executor failed: {e}")

        has_critical = len(issues) > 0
        return {
            "all_passed": not has_critical,
            "issues": issues,
            "has_critical_issues": has_critical,
        }

    async def _store_frank_learning(
        self,
        repo_state: dict[str, Any],
        failure_patterns: dict[str, Any],
        result: ReasoningResult,
    ) -> None:
        logger.info(
            "Frank learning: %d code files, %d test files, %d failures found",
            len(repo_state.get("code", [])),
            len(repo_state.get("tests", [])),
            len(failure_patterns.get("failures", [])),
        )

    async def _store_mason_learning(
        self,
        diagnostics: dict[str, Any],
        result: ReasoningResult,
    ) -> None:
        logger.info(
            "Mason learning: gates_passed=%s, issues=%d, tools_used=%d",
            diagnostics.get("all_passed"),
            len(diagnostics.get("issues", [])),
            len(getattr(result, "tool_history", [])),
        )

    def _utc_now(self) -> datetime:
        return datetime.now(UTC)
