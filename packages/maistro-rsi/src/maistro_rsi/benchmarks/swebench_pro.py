"""SWE-Bench Pro adapter — long-horizon, multi-file code-fix evaluation.

SWE-Bench Pro (arXiv:2509.16941, scaleapi/SWE-bench_Pro-os) raises the bar over
the original SWE-bench: tasks average ~107 lines changed across ~4 files, drawn
from 41 actively-maintained repos, with a held-out split kept private to resist
overfitting. Top models currently score ~23% on its public set versus 70%+ on
SWE-bench Verified — meaning it still has headroom to track a capability
trendline rather than being saturated, which is exactly the property that
makes a benchmark useful for measuring recursive self-improvement over time.

This adapter mirrors the shape of `maistro_evolve.benchmarks.swebench` (same
`BenchmarkRunner` signature, same `prompt_builder`/`scoring` helpers) so it
slots into the existing `EvalHarness` — but scores against multi-file task
samples and weighs whether a fix actually touches the files it needs to,
rather than rewarding single-file patches on inherently cross-cutting bugs.

Ships with a small embedded sample set for offline/dev scoring. Wiring the
full held-out split requires fetching scaleapi/SWE-bench_Pro-os at run time —
left as an extension point (`load_remote_samples`) rather than a hard
dependency, so the harness keeps working without network access.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from maistro_evolve.benchmarks.prompt_builder import (
    build_messages,
    build_model_config,
    build_system_prompt,
)
from maistro_evolve.benchmarks.scoring import judge_score
from maistro_evolve.types import EvalResult, PipelineGenome

# A small, hand-written sample of multi-file long-horizon tasks in the spirit
# of SWE-Bench Pro's public set — enough to exercise the scoring path offline.
# `load_remote_samples` is the seam for pulling the real (much larger) dataset.
SWEBENCH_PRO_SAMPLES: list[dict[str, Any]] = [
    {
        "id": "sbp_01",
        "problem": (
            "Pagination is broken: the API layer computes `offset` from "
            "`page_size` but the repository layer still expects a raw "
            "`limit`/`offset` pair, and the response serializer drops the "
            "`total_count` field the frontend depends on."
        ),
        "files": [
            "api/routes/listings.py",
            "repository/listings_repo.py",
            "serializers/listing_serializer.py",
        ],
        "expected_keywords": ["offset", "limit", "total_count", "page_size"],
        "min_files_touched": 2,
    },
    {
        "id": "sbp_02",
        "problem": (
            "Cache invalidation race: writes to `UserProfile` update Postgres "
            "but the Redis-backed read cache in the service layer isn't "
            "invalidated, and a background job re-warms it from a stale "
            "replica, so profile edits intermittently revert."
        ),
        "files": [
            "services/profile_service.py",
            "cache/redis_cache.py",
            "jobs/cache_warmer.py",
        ],
        "expected_keywords": ["invalidate", "cache", "replica", "stale"],
        "min_files_touched": 2,
    },
    {
        "id": "sbp_03",
        "problem": (
            "Webhook retries duplicate side effects: the dispatcher retries on "
            "any 5xx without an idempotency key, the handler re-creates "
            "billing records on replay, and the audit log records the retry "
            "as a brand-new event instead of a redelivery."
        ),
        "files": [
            "webhooks/dispatcher.py",
            "billing/handlers.py",
            "audit/log_writer.py",
        ],
        "expected_keywords": ["idempotency", "retry", "redelivery", "duplicate"],
        "min_files_touched": 3,
    },
]


def load_remote_samples() -> list[dict[str, Any]]:
    """Extension point for the full held-out split.

    Intentionally unimplemented: fetching scaleapi/SWE-bench_Pro-os requires
    network access and a much larger execution environment (per-task repo
    checkouts + test harnesses) than the embedded sample set needs. Wire this
    up once the microVM backend can run real per-task setups (see
    `maistro_rsi.sandbox.microvm`).
    """
    raise NotImplementedError(
        "Remote SWE-Bench Pro dataset loading not wired up yet — "
        "use the embedded SWEBENCH_PRO_SAMPLES for offline scoring."
    )


def _extract_referenced_files(response: str, candidate_files: list[str]) -> set[str]:
    """Which of the task's files does the response actually touch?

    Looks for the literal path or its basename — agents commonly reference
    `listings_repo.py` without the directory prefix.
    """
    lower = response.lower()
    touched = set()
    for path in candidate_files:
        basename = path.rsplit("/", 1)[-1]
        if path.lower() in lower or basename.lower() in lower:
            touched.add(path)
    return touched


def _score_multi_file_fix(response: str, sample: dict[str, Any]) -> float:
    """Reward fixes that span the files the bug actually requires.

    A patch that only touches one file when the bug is a cross-cutting
    consistency issue (the norm for SWE-Bench Pro-style tasks) is — by
    construction — incomplete, so `files_touched` dominates the score.
    """
    score = 0.0
    max_score = 0.0

    code_blocks = re.findall(r"```(?:\w*)\s*(.*?)```", response, re.DOTALL)
    code_text = "\n".join(code_blocks) if code_blocks else response

    files_touched = _extract_referenced_files(response, sample["files"])
    min_files = sample.get("min_files_touched", 1)
    max_score += 0.5
    score += min(1.0, len(files_touched) / max(1, min_files)) * 0.5

    expected_keywords = sample.get("expected_keywords", [])
    if expected_keywords:
        max_score += 0.35
        found = sum(1 for kw in expected_keywords if kw.lower() in code_text.lower())
        score += (found / len(expected_keywords)) * 0.35

    if len(code_text.strip()) > 80:
        max_score += 0.15
        score += 0.15

    if max_score == 0:
        return 0.0
    return float(min(1.0, score / max_score))


async def _judge_cross_file_consistency(
    problem: str,
    files: list[str],
    response: str,
    llm_call: Any,
) -> float:
    code_blocks = re.findall(r"```(?:\w*)\s*(.*?)```", response, re.DOTALL)
    proposed_fix = "\n".join(code_blocks) if code_blocks else response[:800]

    judge_prompt = (
        "You are reviewing a proposed multi-file bug fix on a scale of 0-10.\n\n"
        f"Problem (spans these files: {', '.join(files)}):\n{problem}\n\n"
        f"Proposed fix:\n{proposed_fix}\n\n"
        "Consider: does it address the root cause across ALL the affected "
        "files, or just patch the symptom in one place? "
        "Respond with ONLY a number 0-10."
    )

    try:
        judge_response = await asyncio.wait_for(
            llm_call(
                [
                    {
                        "role": "system",
                        "content": "You are a strict code reviewer. Respond with only a number.",
                    },
                    {"role": "user", "content": judge_prompt},
                ],
                temperature=0.0,
                max_tokens=10,
            ),
            timeout=25.0,
        )
        return judge_score(judge_response)
    except (TimeoutError, Exception):
        return 0.0


async def run_swebench_pro(genome: PipelineGenome, llm_call: Any) -> EvalResult:
    start = time.monotonic()
    system_prompt = build_system_prompt(genome)
    model_config = build_model_config(genome)

    code_system = (
        system_prompt + "\n\n"
        "You are an expert software engineer working on a large, real-world "
        "codebase. Bug reports here typically require coordinated changes "
        "across multiple files — identify every file that needs to change, "
        "explain why, and provide the corrected code for each in its own "
        "```python``` block labeled with its file path."
    )

    total_score = 0.0
    evaluated = 0
    total_cost = 0.0
    samples = len(SWEBENCH_PRO_SAMPLES)

    for sample in SWEBENCH_PRO_SAMPLES:
        user_msg = (
            f"## Bug Report\n{sample['problem']}\n\n"
            f"## Affected files\n" + "\n".join(f"- `{f}`" for f in sample["files"]) + "\n\n"
            "Provide the fix for each file that needs to change."
        )
        messages = build_messages(code_system, user_msg)

        try:
            if llm_call is not None:
                response = await asyncio.wait_for(
                    llm_call(
                        messages,
                        temperature=model_config.get("temperature", 0.2),
                        max_tokens=model_config.get("max_tokens", 3072),
                    ),
                    timeout=60.0,
                )

                static_score = _score_multi_file_fix(response, sample)
                if static_score >= 0.7:
                    total_score += static_score
                else:
                    judged = await _judge_cross_file_consistency(
                        sample["problem"], sample["files"], response, llm_call
                    )
                    total_score += max(static_score, judged)
                    total_cost += 0.0015

                total_cost += 0.003
                evaluated += 1
            else:
                total_score += _heuristic_score(sample)
                evaluated += 1
        except (TimeoutError, Exception):
            evaluated += 1

    avg_score = total_score / max(evaluated, 1)
    elapsed = time.monotonic() - start

    return EvalResult(
        benchmark="proxy_swebench_pro",
        score=round(avg_score, 4),
        cost_usd=round(total_cost, 4),
        duration_seconds=round(elapsed, 3),
        samples_evaluated=evaluated,
        metadata={
            "total_samples": samples,
            "fidelity": "proxy",
            "dataset": "embedded_sample_v0",
            # Unlike every maistro_evolve proxy scorer (which raises rather than
            # fabricate a score), this adapter falls back to a candidate-independent
            # random score (_heuristic_score) when no model is available — a
            # deliberate choice per runner.py's own comment, so the RSI autorun
            # loop degrades rather than halts when idle-quota headroom is
            # temporarily exhausted. `stub` is maistro_evolve's established,
            # already-consumed noise flag (see reflect.py/hyper_mutator.py:
            # "SPEC-202 honesty: a stub score is noise — never verify against
            # it"). Before this fix it was never set here, so a fabricated
            # score was silently eligible to be treated as real signal by
            # anything sharing this EvalHarness — exactly the gap that flag
            # exists to close.
            "stub": llm_call is None,
        },
    )


def _heuristic_score(sample: dict[str, Any]) -> float:
    import random

    min_files = sample.get("min_files_touched", 1)
    base = 0.35 - (min_files * 0.04)
    return float(max(0.05, min(0.6, base + random.uniform(-0.05, 0.1))))
