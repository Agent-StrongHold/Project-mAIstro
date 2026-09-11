"""Benchmark evaluator for programming DAGs.

Scores DAG outputs against SWE-bench / TerminalBench / DeepSWE style criteria.
Used as Signal #3 (eval-judge) for hill-climbing programming pipelines.

The evaluator:
1. Takes the DAG's code output
2. Checks: does it parse? does it have tests? do tests pass?
3. Scores on a rubric: correctness, completeness, test coverage, style
4. Returns a 0-1 score that feeds the optimizer

For now: LLM-as-judge with a strict rubric.
Future: actual test execution in a sandbox.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from maistro.capabilities.binding_store import BindingResolutionError
from maistro.capabilities.governed_invocation import (
    InvocationApprovalRequired,
    InvocationDenied,
)
from maistro.capabilities.providers.llm_gateway import ModelChatRequest
from services.governed_model import (
    _runtime,
    complete,
    control_plane_binding,
    ensure_binding,
    resolve_binding,
)

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
    node_run_id: str = "",
    attempt_id: str = "",
    workspace_id: str = "",
    project_id: str = "",
) -> dict[str, Any]:
    """Score a coding pipeline's output through the canonical model egress.

    The evaluator is an operation on the already-admitted canonical Run. Its
    stable operation identifiers correlate the resulting Invocation without
    inventing a second execution lifecycle for the optimizer.
    """
    if not all((run_id, node_run_id, attempt_id, workspace_id, project_id)):
        return {
            "error": "evaluation requires canonical Run/NodeRun/Attempt and scope",
            "error_kind": "authorization",
            "total": 0,
            "pass": False,
        }

    messages = [
        {"role": "system", "content": EVAL_RUBRIC},
        {
            "role": "user",
            "content": f"TASK:\n{task}\n\nPLAN:\n{plan[:2000]}\n\nCODE:\n{code[:4000]}\n\nREVIEW:\n{review[:1000]}",
        },
    ]
    try:
        runtime = _runtime()
        binding = control_plane_binding(
            binding_id=f"benchmark-evaluation:{run_id}",
            workspace_id=workspace_id,
            project_id=project_id,
        )
        binding = await ensure_binding(runtime, binding)
        binding = await resolve_binding(runtime, binding)
        result = await complete(
            runtime=runtime,
            binding=binding,
            run_id=run_id,
            node_run_id=node_run_id,
            attempt_id=attempt_id,
            effect_key="benchmark.evaluation:judge",
            request=ModelChatRequest(
                model=model,
                messages=messages,
                max_tokens=2048,
                temperature=0.0,
                response_format={"type": "json_object"},
            ),
        )
        content = result.body["choices"][0]["message"]["content"]
        score = json.loads(content)
        score["invocation_id"] = result.invocation_id
        score["usage"] = result.usage.model_dump(mode="json") if result.usage else None
        return score
    except (BindingResolutionError, InvocationDenied, InvocationApprovalRequired) as exc:
        logger.warning("benchmark_eval_authorization_failed: %s", exc)
        return {"error": str(exc), "error_kind": "authorization", "total": 0, "pass": False}
    except Exception as exc:
        logger.warning("benchmark_eval_failed: %s", exc)
        return {"error": str(exc), "error_kind": "evaluation", "total": 0, "pass": False}


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
        node_run_id=f"benchmark-evaluation-node:{run_result.get('run_id') or ''}",
        attempt_id=f"benchmark-evaluation-attempt:{run_result.get('run_id') or ''}",
        workspace_id=str(run_result.get("workspace_id") or ""),
        project_id=str(run_result.get("project_id") or ""),
    )
    logger.info(
        "benchmark_score task=%s total=%s pass=%s", task[:40], score.get("total"), score.get("pass")
    )
    return score
