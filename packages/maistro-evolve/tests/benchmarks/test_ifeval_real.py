"""Real-fidelity IFEval: official corpus, official vendored grader.

These tests assert two different kinds of thing, and the distinction matters:

* **Corpus/provenance invariants** run unconditionally. The corpus is committed,
  so its size, checksum and split are always checkable — and they are the exam's
  identity, so a test that skips when a dep is missing would let the exam drift
  silently.
* **Grader behaviour** needs the `ifeval` extra (absl-py, immutabledict, nltk +
  punkt, langdetect), so those tests skip when it is absent rather than failing a
  bare install. What they must never do is pass by accident on a partial grader —
  hence the explicit compliant/non-compliant pairs below, which pin that the
  official verifier is really deciding.
"""

from __future__ import annotations

import hashlib
from typing import Any

import pytest

from maistro_evolve.benchmarks import ifeval_real
from maistro_evolve.benchmarks.ifeval_real import (
    IFEvalUnavailableError,
    load_corpus,
    run_ifeval_real,
    split_of,
)

from .conftest import make_genome

# The published IFEval corpus: 541 prompts, 25 instruction types.
_CORPUS_SIZE = 541
_INSTRUCTION_TYPES = 25

_grader_available = True
_grader_skip = ""
try:  # pragma: no cover - environment-dependent
    from maistro_evolve.benchmarks.third_party.ifeval import evaluation_lib  # noqa: F401
except Exception as exc:  # pragma: no cover
    _grader_available = False
    _grader_skip = f"official IFEval grader unavailable ({type(exc).__name__}: {exc})"

needs_grader = pytest.mark.skipif(not _grader_available, reason=_grader_skip)


@pytest.fixture
def pin_corpus(monkeypatch: pytest.MonkeyPatch):
    """Narrow the corpus to specific records for a test.

    Deliberately a monkeypatch and not a ``corpus_override=`` argument on
    ``run_ifeval_real``. A public way to say "score me against this prompt list
    instead" would make the load-time checksum decorative — the RSI loop could
    hand the grader an easy corpus and still be labelled ``fidelity: real``. The
    guard belongs in production code; the bypass belongs in the test harness.
    """

    def pin(records: list[dict[str, Any]]) -> None:
        monkeypatch.setattr(ifeval_real, "load_corpus", lambda split="all": list(records))

    return pin


class TestAvailability:
    def test_probe_matches_this_environment(self) -> None:
        """`available()` is the optional-includes gate: True where the ifeval
        extra + punkt data are installed, False with an actionable hint where
        not. Environment-agnostic assertion on purpose — CI without the extra
        and a dev box with it must both pass this test."""
        ok, reason = ifeval_real.available()
        assert isinstance(ok, bool)
        if ok:
            assert reason == ""
        else:
            assert "maistro-evolve[ifeval]" in reason or "punkt" in reason

    def test_missing_corpus_probes_unavailable(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(ifeval_real, "_CORPUS", tmp_path / "absent.jsonl")
        ok, reason = ifeval_real.available()
        assert ok is False
        assert "vendor_ifeval.py" in reason


# --------------------------------------------------------------------------- #
# corpus + provenance — always checked, never skipped
# --------------------------------------------------------------------------- #


class TestCorpus:
    def test_corpus_is_the_official_541_prompts(self) -> None:
        records = load_corpus("all")
        assert len(records) == _CORPUS_SIZE
        assert all({"key", "prompt", "instruction_id_list", "kwargs"} <= set(r) for r in records)
        types = {i for r in records for i in r["instruction_id_list"]}
        assert len(types) == _INSTRUCTION_TYPES

    def test_corpus_checksum_is_enforced_at_load(self, tmp_path, monkeypatch) -> None:
        """Loading re-verifies the hash every time, not once in CI.

        The corpus sits on the RSI loop's own writable tree. `vendor_ifeval.py
        --check` runs in CI only, so without a load-time check a candidate could
        append easy prompts between CI runs and inflate its own score with no
        diff to review.
        """
        tampered = tmp_path / "input_data.jsonl"
        original = ifeval_real._CORPUS.read_text(encoding="utf-8")
        tampered.write_text(
            original + '{"key":99999,"prompt":"free point","instruction_id_list":[],"kwargs":[]}\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(ifeval_real, "_CORPUS", tampered)
        with pytest.raises(IFEvalUnavailableError, match="does not match its pinned checksum"):
            load_corpus("all")

    def test_missing_corpus_raises_rather_than_scoring_nothing(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(ifeval_real, "_CORPUS", tmp_path / "absent.jsonl")
        with pytest.raises(IFEvalUnavailableError, match="corpus missing"):
            load_corpus("all")

    def test_pinned_checksum_matches_the_committed_corpus(self) -> None:
        actual = hashlib.sha256(ifeval_real._CORPUS.read_bytes()).hexdigest()
        assert actual == ifeval_real._CORPUS_SHA256


class TestSplit:
    def test_split_is_a_partition(self) -> None:
        train = {r["key"] for r in load_corpus("train")}
        holdout = {r["key"] for r in load_corpus("holdout")}
        every = {r["key"] for r in load_corpus("all")}
        assert not train & holdout
        assert train | holdout == every

    def test_both_sides_cover_every_instruction_type(self) -> None:
        """A positional split would strand whole instruction families on one side.

        The corpus is grouped by prompt family, so slicing by index would give a
        holdout that tests different *skills*, not held-out instances of the same
        skills — and a train/holdout gap would then measure the split, not
        memorization. Hashing the key is what avoids that.
        """
        for split in ("train", "holdout"):
            types = {i for r in load_corpus(split) for i in r["instruction_id_list"]}
            assert len(types) == _INSTRUCTION_TYPES, f"{split} is missing instruction types"

    def test_split_is_deterministic_across_calls(self) -> None:
        keys = [r["key"] for r in load_corpus("all")]
        assert [split_of(k) for k in keys] == [split_of(k) for k in keys]

    def test_holdout_is_a_useful_minority(self) -> None:
        holdout = len(load_corpus("holdout"))
        assert 0.1 < holdout / _CORPUS_SIZE < 0.35, f"holdout is {holdout}/{_CORPUS_SIZE}"


# --------------------------------------------------------------------------- #
# the runner
# --------------------------------------------------------------------------- #


class TestRunIfevalReal:
    async def test_llm_call_none_raises(self) -> None:
        with pytest.raises(ValueError, match="requires an llm_call"):
            await run_ifeval_real(make_genome(), None)

    async def test_rejects_nonsense_concurrency(self) -> None:
        async def llm_call(messages: Any, **kwargs: Any) -> str:
            return "x"

        with pytest.raises(ValueError, match="concurrency must be >= 1"):
            await run_ifeval_real(make_genome(), llm_call, concurrency=0)

    @needs_grader
    async def test_reports_real_fidelity_and_the_four_official_metrics(self) -> None:
        async def llm_call(messages: Any, **kwargs: Any) -> str:
            return "ok"

        result = await run_ifeval_real(make_genome(), llm_call, split="all", max_prompts=25)
        md = result.metadata
        assert md["fidelity"] == "real"
        assert md["check"] == "official_ifeval_verifier"
        assert "instruction_following_eval" in md["grader"]
        for metric in (
            "prompt_level_strict",
            "prompt_level_loose",
            "instruction_level_strict",
            "instruction_level_loose",
        ):
            assert 0.0 <= md[metric] <= 1.0, metric
        # The headline score IS prompt-level strict, not an average of the four.
        assert result.score == md["prompt_level_strict"]
        # Loose is an upper bound on strict, by construction (it retries the
        # verdict against cleaned-up variants of the response).
        assert md["prompt_level_loose"] >= md["prompt_level_strict"]
        assert md["instruction_level_loose"] >= md["instruction_level_strict"]

    @needs_grader
    async def test_the_grader_actually_grades(self, pin_corpus) -> None:
        """A compliant response scores 1.0 and a non-compliant one 0.0.

        Without this, every other test here would pass against a grader that
        returned a constant. The prompts used require *only* all-lowercase, so
        the expected verdict is unambiguous.
        """
        only_lowercase = [
            r
            for r in load_corpus("all")
            if r["instruction_id_list"] == ["change_case:english_lowercase"]
        ]
        assert only_lowercase, "corpus no longer has a lowercase-only prompt to pin against"
        pin_corpus(only_lowercase[:1])

        async def compliant(messages: Any, **kwargs: Any) -> str:
            return "this response is entirely lowercase with no capital letters at all"

        async def non_compliant(messages: Any, **kwargs: Any) -> str:
            return "This Response Clearly Has Capital Letters In It"

        for llm_call, expected in ((compliant, 1.0), (non_compliant, 0.0)):
            result = await run_ifeval_real(make_genome(), llm_call, split="all")
            assert result.score == expected

    @needs_grader
    async def test_errors_are_counted_not_hidden(self) -> None:
        """A failed call scores 0, identically to a response following nothing.

        metadata["errors"] is the only way to tell a degraded gateway from a
        degraded genome, so it is load-bearing rather than diagnostic garnish.
        """

        async def boom(messages: Any, **kwargs: Any) -> str:
            raise RuntimeError("gateway down")

        result = await run_ifeval_real(make_genome(), boom, split="all", max_prompts=4)
        assert result.score == 0.0
        assert result.metadata["errors"] == 4
        assert result.cost_usd == 0.0
        # An all-errors run is emphatically not a publishable zero.
        assert result.metadata["official_comparable"] is False

    @needs_grader
    async def test_only_a_full_clean_unsampled_run_claims_official_comparability(self) -> None:
        """`official_comparable` is the flag that stops a cheap run being quoted.

        541 calls costs real money, so sampled and split runs are the norm — which
        is exactly why the one combination comparable to a published number has to
        be marked explicitly rather than inferred by a reader.
        """

        async def llm_call(messages: Any, **kwargs: Any) -> str:
            return "ok"

        sampled = await run_ifeval_real(make_genome(), llm_call, split="all", max_prompts=10)
        assert sampled.metadata["sampled"] is True
        assert sampled.metadata["official_comparable"] is False

        # A split run covers a subset too, so it is equally not comparable —
        # even unsampled.
        split_run = await run_ifeval_real(make_genome(), llm_call, split="train", max_prompts=5)
        assert split_run.metadata["split"] == "train"
        assert split_run.metadata["official_comparable"] is False

    @needs_grader
    async def test_sampling_is_deterministic(self) -> None:
        """Two runs of the same genome must draw the same prompts.

        Unseeded sampling would make cycle-over-cycle deltas measure the draw
        rather than the genome — the fitness signal would be noise with a trend.
        """
        seen: list[list[str]] = []

        async def recorder(messages: Any, **kwargs: Any) -> str:
            seen.append([m["content"] for m in messages])
            return "ok"

        await run_ifeval_real(make_genome(), recorder, split="all", max_prompts=12)
        first = list(seen)
        seen.clear()
        await run_ifeval_real(make_genome(), recorder, split="all", max_prompts=12)
        assert sorted(map(str, first)) == sorted(map(str, seen))

    @needs_grader
    async def test_failures_are_attributed_to_instruction_types(self) -> None:
        """Per-type failure counts are what reflective prompt evolution can act on.

        "you keep failing punctuation:no_comma" is a usable critique; "you scored
        0.62" is not.
        """

        async def llm_call(messages: Any, **kwargs: Any) -> str:
            return "ok"

        md = (await run_ifeval_real(make_genome(), llm_call, split="all", max_prompts=40)).metadata
        assert md["failures_by_instruction"], "a one-word response should fail many instructions"
        known = {i for r in load_corpus("all") for i in r["instruction_id_list"]}
        assert set(md["failures_by_instruction"]) <= known
        assert all(v > 0 for v in md["failures_by_instruction"].values())
        for trace in md["failures"]:
            assert "key" in trace
