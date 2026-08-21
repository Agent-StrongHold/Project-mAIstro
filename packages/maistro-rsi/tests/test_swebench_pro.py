"""Tests tied to SPEC.md §4 (SWE-Bench Pro adapter) acceptance criteria swebench_pro-1..4."""

from __future__ import annotations

import pytest

from maistro_rsi.benchmarks.swebench_pro import (
    SWEBENCH_PRO_SAMPLES,
    _score_multi_file_fix,
    load_remote_samples,
    run_swebench_pro,
)


def _full_response(sample: dict) -> str:
    files_block = "\n".join(
        f"`{path}`\n```python\n# fix touching {path}\n"
        + " ".join(sample["expected_keywords"])
        + "\n```"
        for path in sample["files"]
    )
    return f"Here are the fixes:\n{files_block}"


def _single_file_response(sample: dict) -> str:
    path = sample["files"][0]
    return f"`{path}`\n```python\n# fix touching only {path}\n```"


class FakeGenome:
    """Minimal stand-in — the adapter only reads `topology.nodes`."""

    class _Topology:
        nodes: tuple = ()

    topology = _Topology()


class TestRunSwebenchPro:
    @pytest.mark.asyncio
    async def test_returns_eval_result_for_full_sample_set(self):
        """swebench_pro-1: result names the benchmark and evaluates every embedded sample."""

        async def llm_call(messages, temperature=0.2, max_tokens=3072):
            # Echo back a full multi-file response for whichever sample is being asked about
            for sample in SWEBENCH_PRO_SAMPLES:
                if sample["problem"][:30] in messages[-1]["content"]:
                    return _full_response(sample)
            return "no idea"

        result = await run_swebench_pro(FakeGenome(), llm_call)

        assert result.benchmark == "proxy_swebench_pro"
        assert result.samples_evaluated == len(SWEBENCH_PRO_SAMPLES)
        assert result.metadata["stub"] is False

    @pytest.mark.asyncio
    async def test_no_llm_call_falls_back_to_a_flagged_stub_score(self):
        """A candidate-independent random score (no model available) must carry
        metadata["stub"] = True — maistro_evolve's reflect.py/hyper_mutator.py
        both refuse to verify against a stub-flagged result ("a stub score is
        noise"), so an unflagged fabricated score here would silently be
        treated as real signal by anything sharing this EvalHarness."""
        result = await run_swebench_pro(FakeGenome(), None)

        assert result.metadata["stub"] is True
        assert result.metadata["fidelity"] == "proxy"


class TestScoreMultiFileFix:
    def test_referencing_every_affected_file_scores_higher_than_one_file(self):
        """swebench_pro-2: a complete multi-file fix outscores a single-file patch on the same bug."""
        sample = SWEBENCH_PRO_SAMPLES[0]

        full_score = _score_multi_file_fix(_full_response(sample), sample)
        partial_score = _score_multi_file_fix(_single_file_response(sample), sample)

        assert full_score > partial_score

    def test_response_with_no_signal_scores_near_zero(self):
        """swebench_pro-3: a response with none of the expected keywords and no code scores ~0."""
        sample = SWEBENCH_PRO_SAMPLES[0]
        score = _score_multi_file_fix("I'm not sure how to help with that.", sample)
        assert score < 0.1


class TestLoadRemoteSamples:
    def test_is_a_documented_extension_point_not_a_silent_stub(self):
        """swebench_pro-4: load_remote_samples raises NotImplementedError rather than returning empty data."""
        with pytest.raises(NotImplementedError):
            load_remote_samples()
