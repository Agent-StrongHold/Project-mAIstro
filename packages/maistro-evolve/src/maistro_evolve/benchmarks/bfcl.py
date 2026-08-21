from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from ..types import EvalResult, PipelineGenome
from .datasets import BFCL_SAMPLES
from .prompt_builder import build_messages, build_model_config, build_system_prompt
from .scoring import extract_json_from_response, function_call_match


def _extract_tool_call(response: str) -> dict[str, Any] | None:
    data = extract_json_from_response(response)
    if data is not None:
        if isinstance(data, list) and len(data) > 0:
            data = data[0]
        if isinstance(data, dict):
            return data

    action_match = re.search(
        r"(?:call|invoke|use|execute)\s+(\w+)\s*\(([^)]*)\)",
        response,
        re.IGNORECASE,
    )
    if action_match:
        name = action_match.group(1)
        args_str = action_match.group(2).strip()
        args: dict[str, Any] = {}
        if args_str:
            for pair in args_str.split(","):
                if "=" in pair:
                    k, v = pair.split("=", 1)
                    args[k.strip()] = v.strip().strip("\"'")
        return {"name": name, "parameters": args}

    return None


def _name_score(actual_name: str, expected_name: str) -> float:
    if actual_name == expected_name:
        return 1.0
    if expected_name.replace("_", "") in actual_name.replace("_", ""):
        return 0.8
    if expected_name.replace("_", " ") in actual_name:
        return 0.6
    return 0.0


def _score_numeric_param(actual_val: Any, expected_val: Any) -> float:
    try:
        if float(actual_val) == float(expected_val):
            return 1.0
        if abs(float(actual_val) - float(expected_val)) < 1.0:
            return 0.5
        return 0.0
    except (ValueError, TypeError):
        if str(expected_val).lower() in str(actual_val).lower():
            return 0.5
        return 0.0


def _score_single_param(actual_val: Any, expected_val: Any, response: str) -> float:
    if actual_val is None:
        text = response.lower()
        if isinstance(expected_val, str) and expected_val.lower() in text:
            return 0.5
        return 0.0
    if isinstance(expected_val, bool):
        return 1.0 if str(actual_val).lower() == str(expected_val).lower() else 0.0
    if isinstance(expected_val, (int, float)):
        return _score_numeric_param(actual_val, expected_val)
    if isinstance(expected_val, str):
        if expected_val.lower() == str(actual_val).lower():
            return 1.0
        if expected_val.lower() in str(actual_val).lower():
            return 0.7
    return 0.0


def _param_score(call: dict[str, Any], expected_params: dict[str, Any], response: str) -> float:
    actual_params = call.get("parameters") or call.get("arguments") or call.get("args") or {}
    if not isinstance(actual_params, dict):
        actual_params = {}

    total = len(expected_params)
    if total == 0:
        return 1.0

    matches = 0.0
    for key, expected_val in expected_params.items():
        matches += _score_single_param(actual_params.get(key), expected_val, response)
    return matches / total


def _score_tool_call(
    response: str,
    sample: dict[str, Any],
) -> float:
    expected_name = sample["expected_name"].lower()
    expected_params = sample.get("expected_params")

    fc_score = function_call_match(response, sample["expected_name"], expected_params)
    if fc_score > 0:
        return fc_score

    call = _extract_tool_call(response)
    if call is None:
        response_lower = response.lower()
        if (
            expected_name.replace("_", " ") in response_lower
            or expected_name.replace("_", "") in response_lower
        ):
            return 0.5 * 0.5
        return 0.0

    actual_name = str(call.get("name") or call.get("function") or call.get("action") or "").lower()
    name_score = _name_score(actual_name, expected_name)

    param_score = 1.0 if expected_params is None else _param_score(call, expected_params, response)

    return name_score * 0.4 + param_score * 0.6


async def run_bfcl(genome: PipelineGenome, llm_call: Any) -> EvalResult:
    """Score function-calling — structural when a call parses, text-mention otherwise.

    Proxy-tier (SPEC-202): the samples are a small handcrafted set, not the
    official BFCL corpus. The primary path is structural: the response's
    function call is extracted (``extract_json_from_response``) and its name
    and parameters compared field-by-field against the expected call
    (``function_call_match``). But two real fallbacks are NOT structural: if
    no call can be extracted at all, ``_score_tool_call`` still awards 0.25
    for the expected function name merely appearing in prose; and within a
    parsed call, ``_score_single_param`` awards 0.5 for a missing
    parameter's value appearing anywhere in the raw response text. Because
    the fitness hard-gate for this benchmark is 0.20, a response that never
    produces a real function call can still clear it.
    """
    if llm_call is None:
        raise ValueError(
            "run_bfcl requires an llm_call — there is no stub/heuristic "
            "fallback (SPEC-202: never produce a fabricated score)"
        )

    start = time.monotonic()
    system_prompt = build_system_prompt(genome)
    model_config = build_model_config(genome)

    total_score = 0.0
    evaluated = 0
    total_cost = 0.0
    samples = len(BFCL_SAMPLES)

    for sample in BFCL_SAMPLES:
        functions_desc = "\nAvailable functions:\n"
        for fn in sample["functions"]:
            params_str = ", ".join(f"{k}: {v}" for k, v in fn.get("parameters", {}).items())
            functions_desc += f"- {fn['name']}({params_str}): {fn.get('description', '')}\n"

        user_msg = (
            f"{sample['query']}\n\n"
            f"Respond with the function call as a JSON object with 'name' and 'parameters' fields. "
            f'Example: {{"name": "function_name", "parameters": {{...}}}}\n'
            f"{functions_desc}"
        )

        messages = build_messages(system_prompt, user_msg)

        try:
            response = await asyncio.wait_for(
                llm_call(
                    messages,
                    temperature=model_config.get("temperature", 0.1),
                    max_tokens=model_config.get("max_tokens", 1024),
                ),
                timeout=30.0,
            )
            score = _score_tool_call(response, sample)
            total_score += score
            evaluated += 1
            total_cost += 0.001
        except (TimeoutError, Exception):
            evaluated += 1

    avg_score = total_score / max(evaluated, 1)
    elapsed = time.monotonic() - start

    return EvalResult(
        benchmark="proxy_bfcl",
        score=round(avg_score, 4),
        cost_usd=round(total_cost, 4),
        duration_seconds=round(elapsed, 3),
        samples_evaluated=evaluated,
        metadata={"total_samples": samples, "fidelity": "proxy"},
    )
