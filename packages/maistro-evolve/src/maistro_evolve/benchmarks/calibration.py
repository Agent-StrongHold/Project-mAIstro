"""Adversarial calibration harness for the proxy-tier scorers (#384).

Measures how much credit each proxy scorer leaks to *narration-only* output —
responses that maximize narration (tool names in prose, the expected answer
quoted, expected keywords woven in) while doing none of the required work —
and how well each scorer still recognizes *verified* real outcomes.

The fixture responses live here, deliberately held out of ``datasets.py``:
the scorers never train or select against them, so they are held-out probes
with known ground truth — "no work was done" for the narration set, "the
required action / answer was produced" for the verified set.

Per scorer the report carries:

- ``narration_false_positive_rate`` — the false-positive rate the acceptance
  criteria for #384 require: the fraction of narration-only fixtures that
  earned any credit. For the execution scorers (``proxy_bfcl``,
  ``proxy_tau_bench``) anything above 0.0 is a leak, because score can only
  come from a JSON-structured call (#852). For the judge-mediated scorers
  (``proxy_gaia``, ``proxy_ragas``) the narration fixtures are scored through
  the runner's real judge path with a strict verifier, so a nonzero rate
  measures judge/heuristic leakage, not candidate skill.
- ``verified_positive_rate`` — calibration against held-out real outcomes:
  the fraction of known-good fixtures (real structured calls, exact answers,
  grounded answers approved by the strict judge) that score as they should.

Run it offline with a real ``llm_call`` to produce a calibration report for
the promotion evidence, or in tests with deterministic stubs to pin the
no-leak property. This module reports; it does not gate. Gating stays in
``fitness.py`` (hard gates, non-tradeable) — a failing calibration is
evidence for a human, not a silent scoring change.
"""

from __future__ import annotations

import json
from typing import Any

from ..types import PipelineGenome
from .bfcl import run_bfcl
from .datasets import BFCL_SAMPLES, GAIA_SAMPLES, RAGAS_SAMPLES, TAU_BENCH_SAMPLES
from .gaia import run_gaia
from .ragas import run_ragas
from .tau_bench import run_tau_bench

CALIBRATION_ID = "adversarial-narration-v1"

# Verdict the strict calibration judge hands out. Narration earns nothing;
# a grounded, correct answer is approved at the top of the scale.
_STRICT_JUDGE_REJECT = "0"
_STRICT_JUDGE_APPROVE = "10"


def _bfcl_narration(expected_name: str, expected_params: dict[str, Any] | None) -> str:
    """Maximal narration, zero work: the call is *described*, never made.

    Contains the function name, the parameters and their values in fluent
    prose — every string the old substring fallbacks matched on — but no
    JSON object, so there is no observed call to verify.
    """
    params = ", ".join(f"{k} set to {v}" for k, v in (expected_params or {}).items())
    return (
        f"I would start by calling the {expected_name} tool to handle this. "
        f"The {expected_name} call would need {params or 'no parameters'}. "
        f"Once {expected_name} completes, I'll summarize the outcome for you. "
        f"Let me know if you'd like me to proceed with {expected_name}."
    )


def _tau_narration(tool_names: list[str]) -> str:
    """Affirmative AND negated prose mentions — both historically scored."""
    mentioned = ", ".join(tool_names)
    negated = tool_names[0] if tool_names else "the tool"
    return (
        f"I plan to use these tools: {mentioned}. Actually, I cannot invoke "
        f"{negated} in this environment, so I will simply explain what "
        f"{negated} would have returned instead."
    )


def _gaia_narration(answer: str) -> str:
    """The expected answer quoted inside confident-sounding hedged narration.

    Under the pre-#384 scorer this earned 0.9 (raw substring) — above the old
    0.7 threshold that skipped the judge entirely. Under the current scorer
    it is unverified prose: only the judge can decide it.
    """
    return (
        f"After extensive research and careful cross-referencing of sources, "
        f"my analysis suggests the answer is {answer}, though I cannot be "
        f"completely certain. The reasoning process that leads to {answer} "
        f"involves several considerations I'd be happy to walk through."
    )


def _ragas_narration(expected_answer: str) -> str:
    """Keyword-dense narration: every content word of the expected answer,
    woven into generic filler. Maximized static word overlap, zero verified
    substance — the exact response the old >= 0.6 static skip rewarded."""
    filler = (
        "Regarding your question, the key points to consider are as follows. "
        "This topic involves several interrelated aspects worth explaining. "
        "To summarize the discussion and provide helpful context: "
    )
    return filler + expected_answer + " These considerations complete the picture."


def _answer_by_question(samples: list[dict[str, Any]], key: str) -> dict[str, Any]:
    return {s.get("question", s.get("query", "")): s[key] for s in samples}


def strict_judge(approve: bool) -> Any:
    """Build a deterministic strict verifier for calibration runs.

    With ``approve=False`` (the narration suites) it rejects every response —
    narration never convinces it. With ``approve=True`` (the ragas verified
    suite, whose exact-answer responses bypass gaia's exact-match path but
    not ragas's judge-only path) it approves at the top of the scale. A
    deterministic judge keeps the calibration measuring the scorer's
    structure, not the mood of some LLM.
    """

    async def _judge(messages: list[dict[str, str]], **kwargs: Any) -> str:
        return _STRICT_JUDGE_APPROVE if approve else _STRICT_JUDGE_REJECT

    return _judge


async def calibrate_proxy_scorers(genome: PipelineGenome, llm_call: Any) -> dict[str, Any]:
    """Run narration and verified fixture suites through the real proxy runners.

    ``llm_call`` plays the candidate under test; it is driven to produce
    narration-only or verified output per fixture. The judge-mediated scorers
    are given a strict in-repo verifier as their judge so the measured rate
    reflects scorer structure, not judge leniency. Returns a report keyed by
    benchmark identifier; see the module docstring for the fields.
    """
    return {
        "calibration": CALIBRATION_ID,
        "scorers": {
            "proxy_bfcl": await _calibrate_bfcl(genome, llm_call),
            "proxy_tau_bench": await _calibrate_tau(genome, llm_call),
            "proxy_gaia": await _calibrate_gaia(genome, llm_call),
            "proxy_ragas": await _calibrate_ragas(genome, llm_call),
        },
    }


def _fixture_responder(mode: dict[str, str], fallback: str, *, exact: bool = False) -> Any:
    """Deterministic candidate stub shared by the per-scorer calibrators.

    Replies with the canned response whose fixture key the prompt carries.
    User messages are scanned newest-first so a tau-bench follow-up turn
    (simulated tool results appended after the candidate's own call) cannot
    shadow the original prompt; ``exact=True`` is that conversation's
    equality match, where a substring test would let one sample's key leak
    into another's transcript. When no fixture matches — a runner's prompt
    template drifting away from the fixture keys, or a sample edited out
    from under the mode dict — the stub answers ``fallback``: the run
    degrades to zero scores, which the report shows, instead of crashing
    the calibration mid-suite.
    """

    async def _call(messages: list[dict[str, Any]], **kwargs: Any) -> str:
        for message in reversed(messages):
            if message.get("role") != "user":
                continue
            content = message["content"]
            for key, reply in mode.items():
                if content == key if exact else key in content:
                    return reply
        return fallback

    return _call


async def _calibrate_bfcl(genome: PipelineGenome, llm_call: Any) -> dict[str, Any]:
    mention = {
        s["query"]: _bfcl_narration(s["expected_name"], s.get("expected_params"))
        for s in BFCL_SAMPLES
    }
    real_call = {
        s["query"]: json.dumps(
            {"name": s["expected_name"], "parameters": s.get("expected_params", {})}
        )
        for s in BFCL_SAMPLES
    }

    narration = await run_bfcl(genome, _fixture_responder(mention, "I am not sure how to do that."))
    verified = await run_bfcl(
        genome, _fixture_responder(real_call, "I am not sure how to do that.")
    )
    return _rates(narration.score, verified.score, len(BFCL_SAMPLES))


async def _calibrate_tau(genome: PipelineGenome, llm_call: Any) -> dict[str, Any]:
    mention = {
        s["conversation"][-1]["content"]: _tau_narration([t["name"] for t in s["tools"]])
        for s in TAU_BENCH_SAMPLES
    }
    real_calls = {
        s["conversation"][-1]["content"]: json.dumps(
            [{"name": name} for name in s["expected_tool_calls"]]
        )
        for s in TAU_BENCH_SAMPLES
    }

    narration = await run_tau_bench(
        genome, _fixture_responder(mention, "I cannot proceed.", exact=True)
    )
    verified = await run_tau_bench(
        genome, _fixture_responder(real_calls, "I cannot proceed.", exact=True)
    )
    return _rates(narration.score, verified.score, len(TAU_BENCH_SAMPLES))


async def _calibrate_gaia(genome: PipelineGenome, llm_call: Any) -> dict[str, Any]:
    answers = _answer_by_question(GAIA_SAMPLES, "answer")

    narration = await run_gaia(
        genome,
        _fixture_responder({q: _gaia_narration(a) for q, a in answers.items()}, "I am not sure."),
        judge_llm_call=strict_judge(False),
    )
    verified = await run_gaia(
        genome,
        _fixture_responder(dict(answers), "I am not sure."),
        judge_llm_call=strict_judge(False),
    )
    return _rates(narration.score, verified.score, len(GAIA_SAMPLES))


async def _calibrate_ragas(genome: PipelineGenome, llm_call: Any) -> dict[str, Any]:
    expected = {s["question"]: s["expected_answer"] for s in RAGAS_SAMPLES}

    narration = await run_ragas(
        genome,
        _fixture_responder({q: _ragas_narration(a) for q, a in expected.items()}, "I am not sure."),
        judge_llm_call=strict_judge(False),
    )
    verified = await run_ragas(
        genome,
        _fixture_responder(dict(expected), "I am not sure."),
        judge_llm_call=strict_judge(True),
    )
    return _rates(narration.score, verified.score, len(RAGAS_SAMPLES))


def _rates(narration_score: float, verified_score: float, n: int) -> dict[str, Any]:
    """Fold a narration run and a verified run into the per-scorer report.

    The runners average over their sample sets, so with an all-or-nothing
    fixture design (each fixture scores 0 or 1) the run score *is* the rate —
    a single leaked narration fixture shows up as ``1/n``. The leaked-count
    figure is the implied fixture count, reported for the evidence record.
    """
    narration_fpr = round(narration_score, 4)
    verified_rate = round(verified_score, 4)
    return {
        "narration_false_positive_rate": narration_fpr,
        "narration_fixtures": n,
        "narration_false_positives_implied": round(narration_fpr * n),
        "verified_positive_rate": verified_rate,
        "verified_fixtures": n,
        "verified_failures_implied": round((1.0 - verified_rate) * n),
    }
