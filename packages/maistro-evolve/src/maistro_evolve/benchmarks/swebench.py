from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime
from typing import Any

from ..types import EvalResult, PipelineGenome
from .datasets import SWEBENCH_SAMPLES
from .prompt_builder import build_messages, build_model_config, build_system_prompt
from .sandbox_exec import run_function_checks

_FUNCTION_NAME_RE = re.compile(r"def\s+(\w+)\s*\(")


# Evaluator-only cases. None of these arguments or expected values are shown in
# the model prompt. Multiple cases per sample prevent trivial constant-return
# implementations from receiving credit for echoing the demonstrated example.
_HIDDEN_CASES: dict[str, list[tuple[list[Any], Any]]] = {
    "swe_01": [
        ([[[1, [2, [3, [4]]]], 5]], [1, 2, 3, 4, 5]),
        ([[[], ["a", ["b"]], "c"]], ["a", "b", "c"]),
    ],
    "swe_02": [
        (["person@example.com"], True),
        (["person@localhost"], False),
    ],
    "swe_03": [
        (
            [{"outer": {"left": 1}, "keep": 7}, {"outer": {"right": 2}, "new": 9}],
            {"outer": {"left": 1, "right": 2}, "keep": 7, "new": 9},
        ),
        ([{"a": {"x": {"one": 1}}}, {"a": {"x": {"two": 2}}}], {"a": {"x": {"one": 1, "two": 2}}}),
    ],
    "swe_04": [
        (
            ["2025-06-01T12:15:30-05:00"],
            datetime.fromisoformat("2025-06-01T12:15:30-05:00"),
        ),
        (
            ["2026-01-02T03:04:05+05:30"],
            datetime.fromisoformat("2026-01-02T03:04:05+05:30"),
        ),
    ],
    "swe_05": [
        ([[1, 2, 3], 5], [[1, 2, 3]]),
        ([[1, 2, 3, 4], 2], [[1, 2], [3, 4]]),
    ],
    "swe_06": [
        (["Hi hi, HI!"], {"hi": 3}),
        (["cat; dog? cat."], {"cat": 2, "dog": 1}),
    ],
    "swe_07": [
        ([9, "3"], 3.0),
        ([1, "0"], None),
    ],
    "swe_09": [
        (["AnotherCamelCase"], "another_camel_case"),
        (["alreadySnake"], "already_snake"),
    ],
    "swe_10": [
        ([10], 55),
        (
            [500],
            139423224561697880139724382870407283950070256587697307264108962948325571622863290691557658876222521294125,
        ),
    ],
}


def _extract_code(response: str) -> str:
    code_blocks = re.findall(r"```(?:python)?\s*(.*?)```", response, re.DOTALL)
    return "\n".join(code_blocks) if code_blocks else response


def _function_name(buggy_code: str) -> str:
    match = _FUNCTION_NAME_RE.search(buggy_code)
    if match is None:
        raise ValueError(f"could not find a function definition in: {buggy_code!r}")
    return match.group(1)


def _evaluation_cases(sample: dict[str, Any]) -> list[tuple[list[Any], Any]]:
    """Return evaluator-only cases for one proxy sample.

    swe_08's stated defect is asymptotic complexity. Its dataset already keeps
    the large timing input secret from the prompt, so retain that performance
    case and add a second small correctness case.
    """
    sample_id = str(sample["id"])
    if sample_id == "swe_08":
        return [
            (sample["call_args"], sample["expected_value"]),
            ([[3, 1, 3, 2, 1, 4, 2]], [3, 1, 2, 4]),
        ]
    cases = _HIDDEN_CASES.get(sample_id)
    if not cases:
        raise ValueError(f"no hidden evaluator cases registered for {sample_id}")
    return cases


async def run_swebench(genome: PipelineGenome, llm_call: Any) -> EvalResult:
    """Score bug-fix responses using isolated, evaluator-only assertions.

    This remains proxy-tier (SPEC-202): the samples are a small handcrafted
    set, not the official SWE-bench corpus, and there is no real repository
    checkout/test suite. The score is nevertheless execution-grounded. Raw LLM
    code runs only in MAIstro's isolated Docker sandbox, and each sample is
    graded against undisclosed cases rather than the example printed in the
    prompt.
    """
    if llm_call is None:
        raise ValueError(
            "run_swebench requires an llm_call — there is no stub/heuristic "
            "fallback (SPEC-202: never produce a fabricated score)"
        )

    start = time.monotonic()
    system_prompt = build_system_prompt(genome)
    model_config = build_model_config(genome)

    code_system = (
        system_prompt + "\n\n"
        "You are an expert software engineer. When given a bug report, provide a corrected "
        "version of the code wrapped in ```python``` code blocks. Explain the fix briefly."
    )

    total_score = 0.0
    evaluated = 0
    total_cost = 0.0
    samples = len(SWEBENCH_SAMPLES)
    failures: list[dict[str, Any]] = []

    for sample in SWEBENCH_SAMPLES:
        user_msg = (
            f"## Bug Report\n{sample['problem']}\n\n"
            f"## Buggy Code\n```python\n{sample['buggy_code']}\n```\n\n"
            f"Please provide the fixed code. The expected output for test input "
            f"{sample['test_input']} is {sample['expected_output']}."
        )
        messages = build_messages(code_system, user_msg)

        try:
            response = await asyncio.wait_for(
                llm_call(
                    messages,
                    temperature=model_config.get("temperature", 0.2),
                    max_tokens=model_config.get("max_tokens", 2048),
                ),
                timeout=45.0,
            )
            total_cost += 0.002

            code = _extract_code(response)
            function_name = _function_name(sample["buggy_code"])
            passed, detail = await run_function_checks(
                code,
                function_name,
                _evaluation_cases(sample),
            )
            total_score += 1.0 if passed else 0.0
            evaluated += 1
            if not passed and len(failures) < 5:
                failures.append({"id": sample["id"], "detail": detail})
        except Exception as exc:
            evaluated += 1
            if len(failures) < 5:
                failures.append({"id": sample["id"], "detail": f"error: {exc}"})

    avg_score = total_score / max(evaluated, 1)
    elapsed = time.monotonic() - start

    return EvalResult(
        benchmark="proxy_swebench",
        score=round(avg_score, 4),
        cost_usd=round(total_cost, 4),
        duration_seconds=round(elapsed, 3),
        samples_evaluated=evaluated,
        metadata={
            "total_samples": samples,
            "fidelity": "proxy",
            "check": "isolated_hidden_assertion_batch",
            "failures": failures,
        },
    )
