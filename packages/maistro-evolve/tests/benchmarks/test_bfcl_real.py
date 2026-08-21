"""Real-fidelity BFCL: official Python-AST corpus, official vendored ast_checker.

Same two-kinds-of-test structure as ``test_ifeval_real.py``: corpus/provenance
invariants run unconditionally (they are the exam's identity), and grader
behaviour is pinned with explicit compliant/non-compliant pairs so nothing here
can pass against a checker that returns a constant. Unlike IFEval there is no
skip marker — the vendored BFCL checker needs nothing beyond the stdlib.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest

from maistro_evolve.benchmarks import bfcl_real
from maistro_evolve.benchmarks.bfcl_real import (
    BFCLUnavailableError,
    bfcl_split_of,
    load_bfcl_corpus,
    parse_tool_calls,
    run_bfcl_real,
)

from .conftest import make_genome

_EXPECTED = {"simple_python": 400, "multiple": 200, "parallel": 200, "parallel_multiple": 200}


@pytest.fixture
def pin_corpus(monkeypatch: pytest.MonkeyPatch):
    """Narrow the corpus to specific records for a test.

    A monkeypatch, not a runner argument, for the same reason as ifeval_real's
    fixture: a public "grade me against this list instead" parameter would make
    the load-time checksum decorative. See that fixture's docstring.
    """

    def pin(records: list[dict[str, Any]]) -> None:
        monkeypatch.setattr(bfcl_real, "load_bfcl_corpus", lambda split="all": list(records))

    return pin


# --------------------------------------------------------------------------- #
# corpus + provenance — always checked, never skipped
# --------------------------------------------------------------------------- #


class TestCorpus:
    def test_corpus_is_the_official_1000_instances(self) -> None:
        records = load_bfcl_corpus("all")
        assert len(records) == 1000
        by_cat: dict[str, int] = {}
        for r in records:
            by_cat[r["category"]] = by_cat.get(r["category"], 0) + 1
            assert {"id", "question", "function", "ground_truth", "category"} <= set(r)
        assert by_cat == _EXPECTED

    def test_corpus_checksum_is_enforced_at_load(self, tmp_path, monkeypatch) -> None:
        """Same threat as ifeval: the exam sits on the loop's writable tree and
        vendor_bfcl.py --check only runs in CI, so the hash re-verifies on every
        load or a candidate can edit its exam between CI runs."""
        src = bfcl_real._DATA_DIR
        tampered_dir = tmp_path / "data"
        (tampered_dir / "possible_answer").mkdir(parents=True)
        for cat in _EXPECTED:
            (tampered_dir / f"BFCL_v4_{cat}.json").write_bytes(
                (src / f"BFCL_v4_{cat}.json").read_bytes()
            )
            (tampered_dir / "possible_answer" / f"BFCL_v4_{cat}.json").write_bytes(
                (src / "possible_answer" / f"BFCL_v4_{cat}.json").read_bytes()
            )
        # Make one ground-truth answer trivially permissive.
        target = tampered_dir / "possible_answer" / "BFCL_v4_simple_python.json"
        target.write_bytes(target.read_bytes() + b'\n{"id": "free", "ground_truth": []}')
        monkeypatch.setattr(bfcl_real, "_DATA_DIR", tampered_dir)
        with pytest.raises(BFCLUnavailableError, match="does not match its pinned checksum"):
            load_bfcl_corpus("all")

    def test_missing_corpus_raises_rather_than_scoring_nothing(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(bfcl_real, "_DATA_DIR", tmp_path / "absent")
        with pytest.raises(BFCLUnavailableError, match="file missing"):
            load_bfcl_corpus("all")

    def test_pinned_checksums_match_the_committed_corpus(self) -> None:
        for cat, (prompt_sha, answer_sha) in bfcl_real._CATEGORY_SHA256.items():
            prompt_file = bfcl_real._DATA_DIR / f"BFCL_v4_{cat}.json"
            answer_file = bfcl_real._DATA_DIR / "possible_answer" / f"BFCL_v4_{cat}.json"
            assert hashlib.sha256(prompt_file.read_bytes()).hexdigest() == prompt_sha, cat
            assert hashlib.sha256(answer_file.read_bytes()).hexdigest() == answer_sha, cat


class TestSplit:
    def test_split_is_a_partition(self) -> None:
        train = {r["id"] for r in load_bfcl_corpus("train")}
        holdout = {r["id"] for r in load_bfcl_corpus("holdout")}
        every = {r["id"] for r in load_bfcl_corpus("all")}
        assert not train & holdout
        assert train | holdout == every

    def test_both_sides_cover_every_category(self) -> None:
        """The BFCL analogue of ifeval's instruction-type coverage: a split that
        stranded a whole category on one side would test different *skills* per
        side, so a train/holdout gap would measure the split, not memorization."""
        for split in ("train", "holdout"):
            cats = {r["category"] for r in load_bfcl_corpus(split)}
            assert cats == set(_EXPECTED), f"{split} is missing categories"

    def test_split_is_deterministic_across_calls(self) -> None:
        ids = [r["id"] for r in load_bfcl_corpus("all")]
        assert [bfcl_split_of(i) for i in ids] == [bfcl_split_of(i) for i in ids]

    def test_holdout_is_a_useful_minority(self) -> None:
        holdout = len(load_bfcl_corpus("holdout"))
        assert 0.1 < holdout / 1000 < 0.35, f"holdout is {holdout}/1000"


# --------------------------------------------------------------------------- #
# response parsing — adapter-side, ours
# --------------------------------------------------------------------------- #


class TestAvailability:
    def test_bfcl_is_available_on_any_correct_checkout(self) -> None:
        """The vendored checker is stdlib-only — no extra, no infra. This is the
        adapter that guarantees a `real` harness is never empty."""
        ok, reason = bfcl_real.available()
        assert ok is True
        assert reason == ""

    def test_missing_corpus_probes_unavailable_with_a_hint(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(bfcl_real, "_DATA_DIR", tmp_path / "absent")
        ok, reason = bfcl_real.available()
        assert ok is False
        assert "vendor_bfcl.py" in reason

    def test_tampered_corpus_still_probes_available_but_fails_at_load(
        self, tmp_path, monkeypatch
    ) -> None:
        """Availability and integrity are different severities: "can't run" is
        an environment fact the harness routes around; "exam was edited" must
        raise, never be routed around. A tampered corpus therefore probes
        available (all files present) and then load fails hard."""
        src = bfcl_real._DATA_DIR
        tampered_dir = tmp_path / "data"
        (tampered_dir / "possible_answer").mkdir(parents=True)
        for cat in _EXPECTED:
            (tampered_dir / f"BFCL_v4_{cat}.json").write_bytes(
                (src / f"BFCL_v4_{cat}.json").read_bytes()
            )
            (tampered_dir / "possible_answer" / f"BFCL_v4_{cat}.json").write_bytes(
                (src / "possible_answer" / f"BFCL_v4_{cat}.json").read_bytes()
            )
        target = tampered_dir / "BFCL_v4_parallel.json"
        target.write_bytes(target.read_bytes() + b"\n")
        monkeypatch.setattr(bfcl_real, "_DATA_DIR", tampered_dir)
        assert bfcl_real.available()[0] is True
        with pytest.raises(BFCLUnavailableError, match="pinned checksum"):
            load_bfcl_corpus("all")


class TestParseToolCalls:
    def test_plain_array_and_fenced_array_parse(self) -> None:
        calls = '[{"name": "f", "arguments": {"x": 1}}]'
        expected = [{"f": {"x": 1}}]
        assert parse_tool_calls(calls) == expected
        assert parse_tool_calls(f"```json\n{calls}\n```") == expected

    def test_bare_single_call_is_accepted(self) -> None:
        assert parse_tool_calls('{"name": "f", "arguments": {}}') == [{"f": {}}]

    def test_garbage_and_malformed_shapes_are_none(self) -> None:
        assert parse_tool_calls("I would probably call f") is None
        assert parse_tool_calls("[]") is None
        assert parse_tool_calls('[{"name": "f"}]') is None  # no arguments dict
        assert parse_tool_calls('[{"arguments": {}}]') is None  # no name
        assert parse_tool_calls('["f"]') is None


# --------------------------------------------------------------------------- #
# the runner
# --------------------------------------------------------------------------- #


def _oracle_response(record: dict[str, Any]) -> str:
    """A correct answer built from the ground truth's first concrete option."""
    calls = []
    for gt in record["ground_truth"]:
        ((fname, params),) = gt.items()
        args = {}
        for p, options in params.items():
            v = next((o for o in options if o != ""), None)
            if v is not None:
                args[p] = v
        calls.append({"name": fname, "arguments": args})
    return json.dumps(calls)


class TestRunBfclReal:
    async def test_llm_call_none_raises(self) -> None:
        with pytest.raises(ValueError, match="requires an llm_call"):
            await run_bfcl_real(make_genome(), None)

    async def test_rejects_nonsense_concurrency(self) -> None:
        async def llm_call(messages: Any, **kwargs: Any) -> str:
            return "[]"

        with pytest.raises(ValueError, match="concurrency must be >= 1"):
            await run_bfcl_real(make_genome(), llm_call, concurrency=0)

    async def test_the_checker_actually_checks(self, pin_corpus) -> None:
        """Correct call → 1.0; wrong argument value → 0.0; wrong function → 0.0.

        The anchor test: without it, everything else here would pass against a
        grader returning a constant. simple_python_0 asks for a triangle area
        with base 10 and height 5 — the expected verdicts are unambiguous.
        """
        target = next(r for r in load_bfcl_corpus("all") if r["id"] == "simple_python_0")
        pin_corpus([target])
        cases = [
            ('[{"name": "calculate_triangle_area", "arguments": {"base": 10, "height": 5}}]', 1.0),
            ('[{"name": "calculate_triangle_area", "arguments": {"base": 10, "height": 7}}]', 0.0),
            ('[{"name": "compute_area", "arguments": {"base": 10, "height": 5}}]', 0.0),
        ]
        for reply, expected in cases:

            async def llm_call(messages: Any, *, _r=reply, **kwargs: Any) -> str:
                return _r

            result = await run_bfcl_real(make_genome(), llm_call, split="all")
            assert result.score == expected, reply
        assert result.metadata["fidelity"] == "real"
        assert result.metadata["check"] == "official_bfcl_ast_checker"

    async def test_wrong_call_count_fails_parallel_instances(self, pin_corpus) -> None:
        target = next(r for r in load_bfcl_corpus("all") if r["category"] == "parallel")
        assert len(target["ground_truth"]) >= 2
        pin_corpus([target])

        async def one_call_only(messages: Any, **kwargs: Any) -> str:
            return json.loads(json.dumps(_oracle_response(target)))  # full oracle first

        # Oracle (right number of calls) passes...
        result = await run_bfcl_real(make_genome(), one_call_only, split="all")
        assert result.score == 1.0

        # ...and truncating to a single call fails with the official error type.
        async def truncated(messages: Any, **kwargs: Any) -> str:
            calls = json.loads(_oracle_response(target))
            return json.dumps(calls[:1])

        result = await run_bfcl_real(make_genome(), truncated, split="all")
        assert result.score == 0.0
        assert "wrong_count" in result.metadata["failures"][0]["error_type"]

    async def test_unparseable_is_counted_separately_from_wrong(self, pin_corpus) -> None:
        """Formatting failures and reasoning failures need different fixes, and
        reflection can only act on the distinction if the result carries it."""
        pin_corpus(load_bfcl_corpus("all")[:4])

        async def prose(messages: Any, **kwargs: Any) -> str:
            return "I would call a function here"

        result = await run_bfcl_real(make_genome(), prose, split="all")
        assert result.score == 0.0
        assert result.metadata["unparseable_responses"] == 4
        assert result.metadata["errors"] == 0
        assert all(
            f["error_type"] == "adapter:unparseable_response" for f in result.metadata["failures"]
        )

    async def test_errors_are_counted_not_hidden(self, pin_corpus) -> None:
        pin_corpus(load_bfcl_corpus("all")[:3])

        async def boom(messages: Any, **kwargs: Any) -> str:
            raise RuntimeError("gateway down")

        result = await run_bfcl_real(make_genome(), boom, split="all")
        assert result.score == 0.0
        assert result.metadata["errors"] == 3
        assert result.cost_usd == 0.0
        assert result.metadata["official_comparable"] is False

    async def test_only_a_full_clean_unsampled_run_claims_official_comparability(self) -> None:
        async def llm_call(messages: Any, **kwargs: Any) -> str:
            return "[]"

        sampled = await run_bfcl_real(make_genome(), llm_call, split="all", max_prompts=8)
        assert sampled.metadata["sampled"] is True
        assert sampled.metadata["official_comparable"] is False

        split_run = await run_bfcl_real(make_genome(), llm_call, split="holdout", max_prompts=8)
        assert split_run.metadata["split"] == "holdout"
        assert split_run.metadata["official_comparable"] is False

    async def test_per_category_accuracy_is_reported(self, pin_corpus) -> None:
        """The leaderboard-comparable numbers are per category; the headline
        score is our instance-weighted aggregate and must equal their weighted
        mean, not hide a different formula."""
        records = [
            next(r for r in load_bfcl_corpus("all") if r["category"] == "simple_python"),
            next(r for r in load_bfcl_corpus("all") if r["category"] == "parallel"),
        ]
        pin_corpus(records)
        by_question = {r["question"][0][0]["content"]: r for r in records}

        async def oracle_for_simple_only(messages: Any, **kwargs: Any) -> str:
            content = messages[-1]["content"]
            record = next(r for q, r in by_question.items() if q in content)
            if record["category"] == "simple_python":
                return _oracle_response(record)
            return "[]"  # fail the parallel one

        result = await run_bfcl_real(make_genome(), oracle_for_simple_only, split="all")
        cats = result.metadata["accuracy_by_category"]
        assert cats["simple_python"] == 1.0
        assert cats["parallel"] == 0.0
        assert result.score == 0.5

    async def test_sampling_is_deterministic(self) -> None:
        seen: list[str] = []

        async def recorder(messages: Any, **kwargs: Any) -> str:
            seen.append(messages[-1]["content"])
            return "[]"

        await run_bfcl_real(make_genome(), recorder, split="all", max_prompts=10)
        first = sorted(seen)
        seen.clear()
        await run_bfcl_real(make_genome(), recorder, split="all", max_prompts=10)
        assert sorted(seen) == first
