"""Benchmark evaluator for programming DAGs.

Scores DAG outputs against SWE-bench / TerminalBench / DeepSWE style criteria.
Used as Signal #3 (eval-judge) for hill-climbing programming pipelines.

The evaluator:
1. Takes the DAG's code output
2. Checks: does it parse? does it have tests? do tests pass?
3. Scores on a rubric: correctness, completeness, test coverage, style
4. Returns a 0-50 rubric total that feeds the optimizer

Every evaluation is a canonical operation: it mints a one-node child Run of the
evaluated Run (which must exist on the canonical spine) and records its judge
call as an Invocation beneath that child's NodeRun/Attempt (#1088). No model
HTTP happens outside the governed egress, and an evaluation without canonical
records to correlate to refuses instead of inventing identifiers. Configured
Bindings and scoped credentials are operator-owned; this consumer creates neither.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from collections.abc import Awaitable
from dataclasses import dataclass
from typing import Any

from maistro.capabilities.admitted_model import AdmittedModelCalls
from maistro.capabilities.binding_store import BindingResolutionError
from maistro.capabilities.governed_invocation import (
    InvocationApprovalRequired,
    InvocationDenied,
)
from maistro.capabilities.model_chat import ModelCallResult
from maistro.capabilities.providers.llm_gateway import ModelChatRequest
from maistro.credentials.router import CredentialScopeError
from maistro.graph.definitions import Graph, Node
from maistro.quota.invocation_quota import InvocationQuotaDenied
from maistro.runs.execution import AttemptContextFactory
from maistro.runs.lifecycle import InvalidLifecycleTransition, is_reclaimed_attempt, transition_path
from maistro.runs.model import (
    TERMINAL_RUN_STATUSES,
    Attempt,
    AttemptStatus,
    NodeRun,
    Run,
    RunStatus,
)
from maistro.runs.service import RunExecutionService
from maistro.runs.store import RunIntegrityError, RunStore
from maistro.runs.store_boundary import require_admitted_actor
from maistro.runtime import ExecutionCallable, ExecutionRuntime, PythonExecutionRuntime


class BenchmarkEvaluationError(RuntimeError):
    """No valid score exists; callers must not use this failure as a baseline."""

    error_kind = "evaluation"

    def __init__(self, message: str, *, evidence: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.attempt_evidence = {"error_kind": self.error_kind, **(evidence or {})}


class BenchmarkAuthorizationError(BenchmarkEvaluationError, PermissionError):
    """The evaluation lacks canonical execution or configured model authority."""

    error_kind = "authorization"


@dataclass(frozen=True)
class BenchmarkRuntime:
    runs: RunStore
    calls: AdmittedModelCalls


def _runtime() -> BenchmarkRuntime:
    """Use the selected Container's configured authority, never ambient keys."""
    from services.engine import get_engine
    from services.governed_model import dag_node_model_calls

    try:
        container = getattr(get_engine().agent_port, "container", None)
        calls = dag_node_model_calls(container)
    except RuntimeError as exc:
        raise BenchmarkAuthorizationError(
            "configured benchmark model authority is unavailable"
        ) from exc
    if calls is None:
        raise BenchmarkAuthorizationError("configured benchmark model authority is unavailable")
    return BenchmarkRuntime(runs=container.run_store, calls=calls)


async def _finish_operation(runtime: BenchmarkRuntime, attempt: Attempt) -> None:
    """The one-shot evaluator declines retries after canonical physical settlement.

    AttemptExecutionService owns leases, cancellation and physical evidence.
    Its generic failure reconciliation parks work for a domain retry decision;
    this domain has no automatic retry and closes those logical records. A
    refusal is FAILED with typed authorization evidence, rather than the old
    manually minted CANCELLED Attempt: no cancellation request occurred. Actual
    cancellation still propagates unchanged through the canonical service.
    """
    if attempt.status is AttemptStatus.COMPLETED:
        return
    node = await runtime.runs.get_node_run(attempt.node_run_id)
    assert node is not None
    run = await runtime.runs.get_run(node.run_id)
    assert run is not None
    target = {
        AttemptStatus.CANCELLED: RunStatus.CANCELLED,
        AttemptStatus.TIMED_OUT: RunStatus.TIMED_OUT,
    }.get(attempt.status, RunStatus.FAILED)
    if is_reclaimed_attempt(attempt):
        target = RunStatus.FAILED
    if run.status is RunStatus.CANCELLED:
        target = RunStatus.CANCELLED
    await _close_operation_node(runtime.runs, node, target, attempt.error)
    run = await runtime.runs.get_run(node.run_id)
    assert run is not None
    if run.status not in TERMINAL_RUN_STATUSES:
        for step in transition_path(run.status, target):
            try:
                await runtime.runs.transition_run(run.run_id, step, error=attempt.error)
            except (InvalidLifecycleTransition, RunIntegrityError):
                current_run = await runtime.runs.get_run(run.run_id)
                if current_run is None or current_run.status not in TERMINAL_RUN_STATUSES:
                    raise
                break


async def _finish_reclaimed_operation(runtime: BenchmarkRuntime, run_id: str) -> None:
    """Close a one-shot recovery winner after late work raises instead of returns."""
    for node in await runtime.runs.list_node_runs(run_id):
        attempts = await runtime.runs.list_attempts(node.node_run_id)
        latest = max(attempts, key=lambda item: item.ordinal, default=None)
        if latest is not None and is_reclaimed_attempt(latest):
            await _finish_operation(runtime, latest)


async def _close_operation_node(
    store: RunStore,
    node: NodeRun,
    target: RunStatus,
    error: str | None,
) -> None:
    if node.status in TERMINAL_RUN_STATUSES:
        return
    for step in transition_path(node.status, target):
        try:
            await store.transition_node_run(node.node_run_id, step, error=error)
        except (InvalidLifecycleTransition, RunIntegrityError):
            current = await store.get_node_run(node.node_run_id)
            if current is None or current.status not in TERMINAL_RUN_STATUSES:
                raise
            return


async def _execute_operation(
    service: RunExecutionService,
    run_id: str,
    judge: ExecutionCallable,
    runtime: ExecutionRuntime,
    models: BenchmarkRuntime,
) -> dict[str, Any]:
    """Signal the canonical owner on cancellation, then drain terminal writes.

    Shielding the service prevents caller cancellation from abandoning a
    durable terminal write. It does not shield live Provider work: cancel_run
    fences the Run and signals its registered runtime owner immediately.
    Repeated cancellation cannot interrupt that cleanup or rewrite evidence.
    """
    attempt_id = ""
    cancellation_requested = False

    def remember_attempt(attempt: Attempt, context: Any) -> Any:
        nonlocal attempt_id
        attempt_id = attempt.attempt_id
        if cancellation_requested:
            raise asyncio.CancelledError
        return context

    async def dispatch(work: Any, context: Any) -> Any:
        if cancellation_requested:
            raise asyncio.CancelledError
        return await judge(work, context)

    task = asyncio.create_task(_run_judgment(service, run_id, dispatch, remember_attempt, models))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        cancellation_requested = True

        await _drain_cleanup(
            _cancel_operation(service, run_id, runtime, attempt_id, task),
            operation_id=run_id,
        )
        raise


async def _run_judgment(
    service: RunExecutionService,
    run_id: str,
    executor: ExecutionCallable,
    context_factory: AttemptContextFactory,
    runtime: BenchmarkRuntime,
) -> dict[str, Any]:
    """Interpret canonical return/raise outcomes inside the owned operation task."""
    try:
        _node, attempt = await service.execute_node(
            run_id,
            "benchmark-evaluation",
            None,
            None,
            executor=executor,
            executor_id="benchmark-evaluation",
            context_factory=context_factory,
        )
    except BenchmarkEvaluationError:
        await _finish_reclaimed_operation(runtime, run_id)
        raise
    if attempt.status is not AttemptStatus.COMPLETED:
        await _finish_operation(runtime, attempt)
        if attempt.status is AttemptStatus.CANCELLED and not is_reclaimed_attempt(attempt):
            raise asyncio.CancelledError
        raise BenchmarkEvaluationError(
            "evaluation Attempt did not complete; recovered work cannot supply a score",
            evidence={"evaluation_run_id": run_id, "attempt_id": attempt.attempt_id},
        )
    assert isinstance(attempt.result, dict)
    return attempt.result


async def _cancel_operation(
    service: RunExecutionService,
    run_id: str,
    runtime: ExecutionRuntime,
    attempt_id: str,
    task: asyncio.Task[dict[str, Any]],
) -> None:
    try:
        await service.cancel_run(run_id)
    except Exception as exc:
        logger.warning(
            "benchmark cancellation fence could not be persisted run=%s error_type=%s",
            run_id,
            type(exc).__name__,
        )
        # Storage failure must not leave live Provider work shielded. This is
        # the same Runtime and canonical Attempt the service already owns.
        if attempt_id:
            await runtime.cancel(attempt_id)
    finally:
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning(
                "benchmark cancellation settlement refused run=%s error_type=%s",
                run_id,
                type(exc).__name__,
            )


async def _drain_cleanup(work: Awaitable[None], *, operation_id: str) -> None:
    cleanup = asyncio.ensure_future(work)
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            continue
        except Exception:
            break
    try:
        cleanup.result()
    except (asyncio.CancelledError, Exception) as exc:
        logger.warning(
            "benchmark cancellation cleanup remains unresolved operation=%s error_type=%s",
            operation_id,
            type(exc).__name__,
        )


async def _admit_operation(service: RunExecutionService, **kwargs: Any) -> Run:
    """A cancelled admission drains its write and closes any committed child."""
    task = asyncio.create_task(service.create_run(**kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:

        async def cancel_admitted() -> None:
            run = await task
            try:
                await service.cancel_run(run.run_id)
            except Exception as exc:
                logger.warning(
                    "benchmark cancellation cleanup remains unresolved run=%s error_type=%s",
                    run.run_id,
                    type(exc).__name__,
                )

        await _drain_cleanup(cancel_admitted(), operation_id="benchmark-admission")
        raise


def _rubric_total(score: dict[str, Any]) -> float:
    """Require each promised dimension before accepting the judge's aggregate."""
    total = 0.0
    for name in ("correctness", "completeness", "test_coverage", "style", "security"):
        criterion = score.get(name)
        if not isinstance(criterion, dict):
            raise ValueError(f"rubric requires {name}")
        value = criterion.get("score")
        if type(value) not in (int, float) or not 0 <= value <= 10:
            raise ValueError(f"{name} score must be finite and in 0..10")
        for field in ("evidence", "fix"):
            if not isinstance(criterion.get(field), str) or not criterion[field].strip():
                raise ValueError(f"{name} requires {field} text")
        total += value
    for field in ("summary", "suggested_prompt_improvement"):
        if not isinstance(score.get(field), str) or not score[field].strip():
            raise ValueError(f"rubric requires {field} text")
    return total


def _score(result: ModelCallResult, run_id: str) -> dict[str, Any]:
    evidence = {
        "invocation_id": result.invocation_id,
        "usage": result.usage.model_dump(mode="json") if result.usage else None,
        "evaluation_run_id": run_id,
    }
    try:
        score = json.loads(result.body["choices"][0]["message"]["content"])
        if not isinstance(score, dict):
            raise ValueError("rubric must be an object")
        expected_total = _rubric_total(score)
        total = score.get("total")
        if (
            type(total) not in (int, float)
            or not 0 <= total <= 50
            or type(score.get("pass")) is not bool
            or score["pass"] != (total >= 35)
            or not math.isclose(total, expected_total, rel_tol=0, abs_tol=1e-9)
            or "error" in score
        ):
            raise ValueError("rubric requires the summed total in 0..50 and a matching pass flag")
    except (ValueError, TypeError, KeyError, IndexError, RecursionError) as exc:
        raise BenchmarkEvaluationError(
            f"invalid evaluation rubric: {exc}", evidence=evidence
        ) from exc
    return {**score, **evidence}


logger = logging.getLogger("hive.benchmark")

EVAL_RUBRIC = """You are a senior engineering reviewer evaluating code output from an AI coding pipeline.

Score the output on these criteria (0-10 each). For EACH criterion, you MUST provide:
- The score
- SPECIFIC evidence from the code (quote the relevant lines or describe what's missing)
- A concrete fix (what exactly should be added/changed, where, and why)

Criteria:
1. CORRECTNESS: Does the code solve the stated task? Would it run without errors? If not, what specific error would occur and on which line?
2. COMPLETENESS: Are all requirements addressed? For each missing requirement, state: what's missing, where it should go, and a code sketch of the fix.
3. TEST_COVERAGE: Are there tests? Do they cover edge cases? List specific test cases that are missing and what they should assert.
4. STYLE: Is the code clean, readable, following best practices? Cite specific anti-patterns with line references.
5. SECURITY: No obvious vulnerabilities? If there are issues, name the vulnerability class (e.g. injection, SSRF) and the exact line.

Return JSON:
{
  "correctness": {"score": N, "evidence": "...", "fix": "..."},
  "completeness": {"score": N, "evidence": "...", "fix": "..."},
  "test_coverage": {"score": N, "evidence": "...", "fix": "..."},
  "style": {"score": N, "evidence": "...", "fix": "..."},
  "security": {"score": N, "evidence": "...", "fix": "..."},
  "total": N,
  "pass": true/false,
  "summary": "One paragraph: what's good, what's broken, what's the single highest-impact fix",
  "suggested_prompt_improvement": "If the AI that wrote this code had a better prompt, what should it say? Write the improved prompt."
}

"pass" = true if total >= 35 (out of 50). This is the SWE-bench equivalent threshold.
"suggested_prompt_improvement" feeds directly into the optimizer's prompt rewrite proposals.
"""


async def evaluate_code_output(
    task: str,
    plan: str,
    code: str,
    review: str = "",
    model: str = "gemini-3.5-flash",
    *,
    run_id: str = "",
    workspace_id: str = "",
    project_id: str = "",
) -> dict[str, Any]:
    """Judge an admitted Run through configured Bindings and a leased child Run.

    Failure raises a typed error, never a numeric score. A completed model
    Invocation remains completed even if its rubric cannot be accepted.
    """
    if not all((run_id.strip(), workspace_id.strip(), project_id.strip())):
        raise BenchmarkAuthorizationError(
            "evaluation requires the canonical Run and its Workspace/Project scope"
        )
    runtime = _runtime()
    parent = await runtime.runs.get_run(run_id)
    if parent is None or (parent.workspace_id, parent.project_id) != (workspace_id, project_id):
        raise BenchmarkAuthorizationError(
            "evaluation scope does not match its canonical parent Run"
        )
    try:
        actor = require_admitted_actor(parent.actor_principal_id)
    except ValueError as exc:
        raise BenchmarkAuthorizationError(str(exc)) from exc

    async def reconcile(attempt: Attempt) -> None:
        await _finish_operation(runtime, attempt)

    execution_runtime = PythonExecutionRuntime()
    service = RunExecutionService(
        store=runtime.runs,
        runtime=execution_runtime,
        reconciler=reconcile,
    )
    try:
        run = await _admit_operation(
            service,
            graph=Graph(
                workspace_id=workspace_id,
                project_id=project_id,
                name="benchmark-evaluation",
                nodes=[Node(node_id="benchmark-evaluation", node_type="evaluation")],
            ),
            parent_run_id=run_id,
            actor_principal_id=actor,
            provenance={
                "admission_source": "benchmark-evaluation",
                "operation": "benchmark-evaluation",
                "evaluated_run_id": run_id,
                "evaluator": "benchmark_eval",
            },
            initial_status=RunStatus.QUEUED,
        )
    except (LookupError, RunIntegrityError, ValueError) as exc:
        raise BenchmarkAuthorizationError(str(exc)) from exc

    async def judge(_work: Any, _context: Any) -> dict[str, Any]:
        try:
            result = await runtime.calls.complete(
                effect_key="benchmark.evaluation:judge",
                request=ModelChatRequest(
                    model=model,
                    messages=[
                        {"role": "system", "content": EVAL_RUBRIC},
                        {
                            "role": "user",
                            "content": f"TASK:\n{task}\n\nPLAN:\n{plan[:2000]}\n\nCODE:\n{code[:4000]}\n\nREVIEW:\n{review[:1000]}",
                        },
                    ],
                    max_tokens=2048,
                    temperature=0.0,
                    response_format={"type": "json_object"},
                ),
            )
        except (
            BindingResolutionError,
            InvocationDenied,
            InvocationApprovalRequired,
            InvocationQuotaDenied,
            CredentialScopeError,
            RunIntegrityError,
        ) as exc:
            raise BenchmarkAuthorizationError(str(exc)) from exc
        except Exception as exc:
            raise BenchmarkEvaluationError(str(exc)) from exc
        return _score(result, run.run_id)

    return await _execute_operation(service, run.run_id, judge, execution_runtime, runtime)


async def evaluate_dag_run(run_result: dict[str, Any], task: str) -> dict[str, Any]:
    """Evaluate a full DAG run result."""
    node_results = run_result.get("node_results", {})

    # Use all node outputs regardless of key names
    all_outputs = [nr.get("response", "") for nr in node_results.values() if nr.get("success")]

    # Split into plan/code/review by position (first=plan, last=review, middle=code)
    if len(all_outputs) >= 3:
        plan, code, review = all_outputs[0], "\n".join(all_outputs[1:-1]), all_outputs[-1]
    elif len(all_outputs) == 2:
        plan, code, review = all_outputs[0], all_outputs[1], ""
    elif len(all_outputs) == 1:
        plan, code, review = all_outputs[0], "", ""
    else:
        plan, code, review = "", "", ""

    score = await evaluate_code_output(
        task,
        plan,
        code,
        review,
        run_id=str(run_result.get("run_id") or ""),
        workspace_id=str(run_result.get("workspace_id") or ""),
        project_id=str(run_result.get("project_id") or ""),
    )
    logger.info(
        "benchmark_score task=%s total=%s pass=%s", task[:40], score.get("total"), score.get("pass")
    )
    return score
