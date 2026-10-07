from __future__ import annotations

import asyncio
import time
from typing import Any

from ..types import EvalResult, PipelineGenome
from .datasets import BFCL_SAMPLES
from .prompt_builder import build_messages, build_model_config, build_system_prompt
from .scoring import extract_json_from_response, function_call_match


def _extract_tool_call(response: str) -> dict[str, Any] | None:
    """Structured call extraction only (#852).

    Only JSON-shaped calls count. The historical prose fallback parsed
    ``call name(args...)`` out of free text, so a sentence mentioning the
    tool name qualified as a call.
    """
    data = extract_json_from_response(response)
    if data is not None:
        if isinstance(data, list) and len(data) > 0:
            data = data[0]
        if isinstance(data, dict):
            return data
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
        # #852: non-numeric observed values earn nothing — the old substring
        # comparison awarded 0.5 for format coincidence, not a correct value.
        return 0.0


def _score_single_param(actual_val: Any, expected_val: Any) -> float:
    """Grade one parameter from the observed structured call only (#852).

    A missing parameter scores 0.0; the historical fallback scanned the raw
    response text for the expected value and awarded 0.5 for its mere
    appearance anywhere in prose.
    """
    if actual_val is None:
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


def _param_score(call: dict[str, Any], expected_params: dict[str, Any]) -> float:
    actual_params = call.get("parameters") or call.get("arguments") or call.get("args") or {}
    if not isinstance(actual_params, dict):
        actual_params = {}

    total = len(expected_params)
    if total == 0:
        return 1.0

    matches = 0.0
    for key, expected_val in expected_params.items():
        matches += _score_single_param(actual_params.get(key), expected_val)
    return matches / total


def _score_tool_call(
    response: str,
    sample: dict[str, Any],
) -> float:
    """Score a structured function call; prose mentions earn nothing (#852).

    The primary path is structural: the response's JSON call is extracted and
    its name/parameters compared against the expected call. The historical
    fallback that awarded 0.25 for the expected name merely appearing in
    prose is removed — a response with no structured call scores 0.0.
    """
    expected_params = sample.get("expected_params")

    fc_score = function_call_match(response, sample["expected_name"], expected_params)
    if fc_score > 0:
        return fc_score

    call = _extract_tool_call(response)
    if call is None:
        return 0.0

    actual_name = str(call.get("name") or call.get("function") or call.get("action") or "").lower()
    name_score = _name_score(actual_name, sample["expected_name"].lower())

    param_score = 1.0 if expected_params is None else _param_score(call, expected_params)

    return name_score * 0.4 + param_score * 0.6


async def run_bfcl(genome: PipelineGenome, llm_call: Any) -> EvalResult:
    """Score function-calling structurally, with no prose fallback (#852).

    Proxy-tier (SPEC-202): the samples are a small handcrafted set, not the
    official BFCL corpus. Every point comes from a JSON-structured call: the
    name (via ``function_call_match`` or the extracted call) and each
    expected parameter's observed value. Prose mention of the function name,
    and missing parameters whose value happens to appear in the response
    text, earn nothing — the historical 0.25/0.5 fallbacks could clear the
    0.20 hard gate without any real call.
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
        metadata={
            "total_samples": samples,
            "fidelity": "proxy",
            # Champion-selection provenance (#384): every point comes from the
            # JSON-structured call match — never from prose (#852).
            "evidence": {"method": "structured-call-match"},
        },
    )
