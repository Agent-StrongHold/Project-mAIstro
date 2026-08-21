from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

from ..types import EvalResult, PipelineGenome
from .datasets import IFEVAL_SAMPLES
from .prompt_builder import build_messages, build_model_config, build_system_prompt
from .scoring import (
    contains_all,
    ends_with,
    exact_match,
    is_valid_json,
    json_field_match,
    sentence_count,
    starts_with,
    word_count,
)


def _rule_contains(response: str, rule: dict[str, Any]) -> float:
    return 1.0 if rule["value"].lower() in response.lower() else 0.0


def _rule_contains_all(response: str, rule: dict[str, Any]) -> float:
    if "values" in rule:
        return contains_all(response, rule["values"])
    return 1.0 if rule["value"].lower() in response.lower() else 0.0


def _rule_not_contains(response: str, rule: dict[str, Any]) -> float:
    return 1.0 if rule["value"].lower() not in response.lower() else 0.0


def _rule_sentence_count(response: str, rule: dict[str, Any]) -> float:
    target: int = rule["value"]
    tolerance: int = rule.get("tolerance", 1)
    actual = sentence_count(response)
    if abs(actual - target) <= tolerance:
        return 1.0
    return max(0.0, 1.0 - abs(actual - target) * 0.2)


def _rule_min_word_count(response: str, rule: dict[str, Any]) -> float:
    return 1.0 if word_count(response) >= rule["value"] else 0.0


def _rule_max_word_count(response: str, rule: dict[str, Any]) -> float:
    return 1.0 if word_count(response) <= rule["value"] else 0.0


def _rule_is_uppercase(response: str, rule: dict[str, Any]) -> float:
    letters = [c for c in response if c.isalpha()]
    return 1.0 if all(c.isupper() for c in letters) else 0.0


def _rule_min_occurrences(response: str, rule: dict[str, Any]) -> float:
    actual = response.count(rule["value"])
    count = rule["count"]
    return 1.0 if actual >= count else actual / count


def _rule_max_occurrences(response: str, rule: dict[str, Any]) -> float:
    actual = response.count(rule["value"])
    count = rule["count"]
    return 1.0 if actual <= count else max(0.0, 1.0 - (actual - count) * 0.3)


_RULE_HANDLERS: dict[str, Callable[[str, dict[str, Any]], float]] = {
    "contains": _rule_contains,
    "contains_all": _rule_contains_all,
    "not_contains": _rule_not_contains,
    "starts_with": lambda response, rule: starts_with(response, rule["value"]),
    "ends_with": lambda response, rule: ends_with(response, rule["value"]),
    "exact_match": lambda response, rule: exact_match(response, rule["value"]),
    "valid_json": lambda response, rule: is_valid_json(response),
    "json_field": lambda response, rule: json_field_match(response, rule["field"], None),
    "sentence_count": _rule_sentence_count,
    "min_word_count": _rule_min_word_count,
    "max_word_count": _rule_max_word_count,
    "is_uppercase": _rule_is_uppercase,
    "min_occurrences": _rule_min_occurrences,
    "max_occurrences": _rule_max_occurrences,
}


def _evaluate_rule(response: str, rule: dict[str, Any]) -> float:
    handler = _RULE_HANDLERS.get(rule["type"])
    if handler is None:
        return 0.5
    return handler(response, rule)


_MAX_FAILURE_TRACES = 5


def _failed_rule_descriptions(response: str, rules: list[dict[str, Any]]) -> list[str]:
    failed: list[str] = []
    for rule in rules:
        if _evaluate_rule(response, rule) < 1.0:
            detail = rule.get("value", rule.get("values", rule.get("field", "")))
            failed.append(f"{rule['type']}={detail!r}" if detail != "" else rule["type"])
    return failed


def _score_response(response: str, rules: list[dict[str, Any]]) -> float:
    if not rules:
        return 1.0
    scores = [_evaluate_rule(response, rule) for rule in rules]
    return sum(scores) / len(scores)


async def run_ifeval(genome: PipelineGenome, llm_call: Any) -> EvalResult:
    """Score instruction-following by checking real, per-instruction rules.

    Proxy-tier (SPEC-202): the samples are a small handcrafted set, not the
    official IFEval corpus. But each check is a genuine structural rule
    (``contains``, ``exact_match``, ``sentence_count``, ``word_count``,
    ``valid_json``, ...) evaluated against the actual response — not scored
    by keyword overlap.
    """
    if llm_call is None:
        raise ValueError(
            "run_ifeval requires an llm_call — there is no stub/heuristic "
            "fallback (SPEC-202: never produce a fabricated score)"
        )

    start = time.monotonic()
    system_prompt = build_system_prompt(genome)
    model_config = build_model_config(genome)

    total_score = 0.0
    samples = len(IFEVAL_SAMPLES)
    evaluated = 0
    total_cost = 0.0
    # Per-sample failure traces feed reflective prompt evolution (reflect.py).
    failures: list[dict[str, Any]] = []

    for sample in IFEVAL_SAMPLES:
        messages = build_messages(system_prompt, sample["instruction"])
        try:
            response = await asyncio.wait_for(
                llm_call(
                    messages,
                    temperature=model_config.get("temperature", 0.3),
                    max_tokens=model_config.get("max_tokens", 2048),
                ),
                timeout=30.0,
            )
            sample_score = _score_response(response, sample["rules"])
            total_score += sample_score
            evaluated += 1
            total_cost += 0.001
            if sample_score < 1.0 and len(failures) < _MAX_FAILURE_TRACES:
                failures.append(
                    {
                        "instruction": sample["instruction"],
                        "failed_rules": _failed_rule_descriptions(response, sample["rules"]),
                        "response_excerpt": response[:200],
                        "score": round(sample_score, 3),
                    }
                )
        except (TimeoutError, Exception):
            total_score += 0.0
            evaluated += 1
            if len(failures) < _MAX_FAILURE_TRACES:
                failures.append(
                    {
                        "instruction": sample["instruction"],
                        "failed_rules": ["error_or_timeout"],
                        "response_excerpt": "",
                        "score": 0.0,
                    }
                )

    avg_score = total_score / max(evaluated, 1)
    elapsed = time.monotonic() - start

    return EvalResult(
        benchmark="proxy_ifeval",
        score=round(avg_score, 4),
        cost_usd=round(total_cost, 4),
        duration_seconds=round(elapsed, 3),
        samples_evaluated=evaluated,
        metadata={"total_samples": samples, "fidelity": "proxy", "failures": failures},
    )
