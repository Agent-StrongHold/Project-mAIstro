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
import os
from typing import Any

from maistro.http import shared_client

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
) -> dict[str, Any]:
    """Score a coding pipeline's output using LLM-as-judge."""
    base = os.environ.get("LITELLM_API_BASE", "")
    key = os.environ.get("LITELLM_API_KEY", "")
    if not base or not key:
        return {"error": "No LLM configured for evaluation"}

    if not base.endswith("/v1"):
        base = base.rstrip("/") + "/v1"

    messages = [
        {"role": "system", "content": EVAL_RUBRIC},
        {
            "role": "user",
            "content": f"TASK:\n{task}\n\nPLAN:\n{plan[:2000]}\n\nCODE:\n{code[:4000]}\n\nREVIEW:\n{review[:1000]}",
        },
    ]

    try:
        async with shared_client(timeout=60.0) as client:
            r = await client.post(
                f"{base}/chat/completions",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": messages,
                    "response_format": {"type": "json_object"},
                },
            )
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            return json.loads(content)
    except Exception as e:
        logger.warning("benchmark_eval_failed: %s", e)
        return {"error": str(e), "total": 0, "pass": False}


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

    score = await evaluate_code_output(task, plan, code, review)
    logger.info(
        "benchmark_score task=%s total=%s pass=%s", task[:40], score.get("total"), score.get("pass")
    )
    return score
