from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from ..types import EvalResult, PipelineGenome
from .datasets import TAU_BENCH_SAMPLES
from .prompt_builder import build_model_config, build_system_prompt
from .scoring import extract_json_from_response


def _extract_tool_calls_from_response(response: str) -> list[str]:
    calls: list[str] = []

    data = extract_json_from_response(response)
    if data is not None:
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    name = item.get("name") or item.get("function") or item.get("action")
                    if name:
                        calls.append(str(name))
        elif isinstance(data, dict):
            name = data.get("name") or data.get("function") or data.get("action")
            if name:
                calls.append(str(name))

    action_matches = re.findall(
        r"(?:call|invoke|use|execute|run)\s+(\w+)",
        response,
        re.IGNORECASE,
    )
    calls.extend(action_matches)

    tool_matches = re.findall(
        r"(?:tool_call|function_call|action)[\"':\s]+(\w+)",
        response,
        re.IGNORECASE,
    )
    calls.extend(tool_matches)

    return list(dict.fromkeys(calls))


def _score_tool_usage(
    response: str,
    sample: dict[str, Any],
) -> float:
    expected = sample["expected_tool_calls"]
    available = [t["name"] for t in sample["tools"]]

    mentioned_tools = [t for t in available if t.lower() in response.lower()]

    extracted = _extract_tool_calls_from_response(response)
    all_mentioned = list(dict.fromkeys(extracted + mentioned_tools))

    if not all_mentioned:
        return 0.0

    matched = 0
    for expected_name in expected:
        for mentioned in all_mentioned:
            if expected_name.lower() == mentioned.lower() or expected_name.lower().replace(
                "_", ""
            ) == mentioned.lower().replace("_", ""):
                matched += 1
                break

    recall = matched / len(expected) if expected else 1.0

    wrong_calls = [
        m
        for m in all_mentioned
        if not any(
            e.lower() == m.lower() or e.lower().replace("_", "") == m.lower().replace("_", "")
            for e in expected
        )
    ]
    precision = 1.0 - (len(wrong_calls) * 0.2)
    precision = max(0.0, precision)

    return recall * 0.7 + precision * 0.3


async def _simulate_turns(
    sample: dict[str, Any],
    messages: list[dict[str, str]],
    llm_call: Any,
    model_config: dict[str, Any],
    max_turns: int,
) -> tuple[str, float]:
    cost = 0.0
    last_response = ""

    for _turn in range(max_turns):
        try:
            response = await asyncio.wait_for(
                llm_call(
                    messages,
                    temperature=model_config.get("temperature", 0.2),
                    max_tokens=model_config.get("max_tokens", 1024),
                ),
                timeout=30.0,
            )
            cost += 0.001
            last_response = response

            extracted = _extract_tool_calls_from_response(response)
            if extracted:
                tool_results = []
                for tool_name in extracted:
                    for tool_def in sample["tools"]:
                        if tool_def["name"] == tool_name:
                            tool_results.append(
                                f"Result from {tool_name}: Success. Operation completed."
                            )
                            break
                    else:
                        tool_results.append(f"Result from {tool_name}: Tool not found.")
                messages.append({"role": "assistant", "content": response})
                messages.append({"role": "user", "content": "\n".join(tool_results)})
            else:
                break
        except (TimeoutError, Exception):
            break

    return last_response, cost


async def run_tau_bench(genome: PipelineGenome, llm_call: Any) -> EvalResult:
    """Score tool-use conversations by name-mention, not verified invocation.

    Proxy-tier (SPEC-202): the samples are a small handcrafted set, not the
    official tau-bench corpus. ``_score_tool_usage`` is NOT a check of what
    the response actually invoked: alongside real JSON/regex-extracted tool
    calls, ``mentioned_tools`` treats ANY available tool's name appearing
    anywhere in the response text as a "call" — including inside a negation
    ("I cannot invoke refund_order" scores identically to actually invoking
    it). The final score is ``recall * 0.7 + precision * 0.3`` over that
    mention set, not recall alone, and both terms inherit the same
    mention-detection weakness.
    """
    if llm_call is None:
        raise ValueError(
            "run_tau_bench requires an llm_call — there is no stub/heuristic "
            "fallback (SPEC-202: never produce a fabricated score)"
        )

    start = time.monotonic()
    system_prompt = build_system_prompt(genome)
    model_config = build_model_config(genome)

    tools_block = (
        "You are a helpful assistant that can use tools to help the user. "
        "When you need to use a tool, output a JSON object with 'name' and 'parameters' fields. "
        "You can call multiple tools if needed."
    )
    effective_system = system_prompt + "\n\n" + tools_block

    total_score = 0.0
    evaluated = 0
    total_cost = 0.0
    samples = len(TAU_BENCH_SAMPLES)

    for sample in TAU_BENCH_SAMPLES:
        messages = list(sample["conversation"])
        full_messages = list(messages)
        full_messages.insert(0, {"role": "system", "content": effective_system})

        try:
            max_turns = sample.get("max_turns", 3)
            response, cost = await _simulate_turns(
                sample, full_messages, llm_call, model_config, max_turns
            )
            total_cost += cost

            all_responses = " ".join(
                m["content"] for m in full_messages if m["role"] == "assistant"
            )
            score = _score_tool_usage(all_responses or response, sample)
            total_score += score
            evaluated += 1
        except (TimeoutError, Exception):
            evaluated += 1

    avg_score = total_score / max(evaluated, 1)
    elapsed = time.monotonic() - start

    return EvalResult(
        benchmark="proxy_tau_bench",
        score=round(avg_score, 4),
        cost_usd=round(total_cost, 4),
        duration_seconds=round(elapsed, 3),
        samples_evaluated=evaluated,
        metadata={"total_samples": samples, "fidelity": "proxy"},
    )
