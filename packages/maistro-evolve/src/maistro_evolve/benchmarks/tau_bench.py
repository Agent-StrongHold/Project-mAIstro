from __future__ import annotations

import asyncio
import time
from typing import Any

from ..types import EvalResult, PipelineGenome
from .datasets import TAU_BENCH_SAMPLES
from .prompt_builder import build_model_config, build_system_prompt
from .scoring import extract_json_from_response


def _extract_tool_calls_from_response(response: str) -> list[str]:
    """Structured tool-call names only (#852).

    Only calls expressed as JSON objects with a ``name``/``function``/
    ``action`` key are observed — the same structured shape the system
    prompt demands. Prose patterns ("I will call refund_order", "I cannot
    invoke refund_order", ``tool_call: name``) are deliberately NOT calls:
    the historical regexes scored a tool *mention* — including a negation —
    identically to an invocation.
    """
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

    return list(dict.fromkeys(calls))


def _normalized(name: str) -> str:
    return name.lower().replace("_", "")


def _score_tool_usage(
    response: str,
    sample: dict[str, Any],
) -> float:
    """Recall/precision over structured observed calls (#852).

    Both terms are computed from the JSON-extracted call set only. A response
    whose prose merely contains tool names (affirmatively or as a negation)
    produces no observed calls and scores 0.0.
    """
    expected = sample["expected_tool_calls"]

    extracted = _extract_tool_calls_from_response(response)
    if not extracted:
        return 0.0

    matched = 0
    for expected_name in expected:
        if any(_normalized(expected_name) == _normalized(mentioned) for mentioned in extracted):
            matched += 1

    recall = matched / len(expected) if expected else 1.0

    wrong_calls = [
        m for m in extracted if not any(_normalized(e) == _normalized(m) for e in expected)
    ]
    precision = max(0.0, 1.0 - (len(wrong_calls) * 0.2))

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
    """Score tool-use conversations by structured, observed calls only.

    Proxy-tier (SPEC-202): the samples are a small handcrafted set, not the
    official tau-bench corpus. Since #852, ``_score_tool_usage`` grades the
    JSON-structured call objects the system prompt explicitly requests —
    never prose. A response that merely mentions a tool name (including
    "I cannot invoke refund_order") produces no observed call and scores 0.0;
    the historical mention-matching (any available tool's name appearing
    anywhere in the text) is gone.
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
        metadata={
            "total_samples": samples,
            "fidelity": "proxy",
            # Champion-selection provenance (#384): every point comes from the
            # JSON-structured observed calls (#852). Outcomes in the
            # multi-turn loop are harness-simulated (proxy fidelity), so the
            # evidence says so explicitly rather than implying a real
            # tool-execution trace.
            "evidence": {"method": "structured-call-match", "outcomes": "simulated"},
        },
    )
