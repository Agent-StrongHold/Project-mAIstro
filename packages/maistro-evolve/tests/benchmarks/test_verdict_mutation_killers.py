"""Mutation killers for the benchmark verdict path (#852).

Each test applies a specific mutant to the verdict-deciding code and asserts
the observable benchmark outcome flips — i.e. a regression reintroducing the
mutant cannot survive this suite:

- **always-pass**: the grader returns success unconditionally;
- **ignored assertion**: the grader stops comparing observed vs expected;
- **inverted predicate**: a rule's comparison is negated;
- **permissive parser**: malformed judge output falls back to a positive
  floor, or unknown rules award half-credit;
- **prose-mention scoring**: tool names mentioned in prose count as calls;
- **spoofed-marker honoring**: candidate stdout markers set the verdict;
- **metadata leak**: failure metadata echoes the hidden rubric.

The empty-body/gate criterion (#852) is pinned end-to-end: a genome whose
judge answers garbage scores 0.0 on GAIA and is rejected by the fitness hard
gate (0.30) — under the historical 0.3 floor it would have passed exactly.
"""

from __future__ import annotations

from typing import Any

import pytest

import maistro_evolve.benchmarks.swebench as swebench_module
from maistro_evolve.benchmarks.gaia import run_gaia
from maistro_evolve.benchmarks.ifeval import _evaluate_rule, run_ifeval
from maistro_evolve.benchmarks.sandbox_exec import _grade_case
from maistro_evolve.benchmarks.scoring import judge_score
from maistro_evolve.benchmarks.tau_bench import _score_tool_usage
from maistro_evolve.fitness import _check_hard_gate

from .conftest import make_genome

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_CASE_ARGS: list[Any] = [[[1, [2, [3, [4]]]], 5]]
_CASE_EXPECTED: list[Any] = [1, 2, 3, 4, 5]
_WRONG_RESULT_OUTPUT = '{"ok": true, "result": [1, 2]}'
_MATCHING_RESULT_OUTPUT = '{"ok": true, "result": [1, 2, 3, 4, 5]}'


# ---------------------------------------------------------------------------
# sandbox_exec verdict-path mutants
# ---------------------------------------------------------------------------


class TestSandboxVerdictMutantsKilled:
    def test_always_pass_mutant_flips_the_verdict(self) -> None:
        """M-always-pass: _grade_case returns (True, 'ok') unconditionally.

        Killed: the honest grader rejects a wrong result; the mutant accepts
        it, so any wrong-body test (e.g. test_wrong_body_mismatch,
        test_result_mismatch_fails_without_leaking_expected) fails under the
        mutant.
        """
        honest_passed, _ = _grade_case(0, _WRONG_RESULT_OUTPUT, _CASE_EXPECTED, 1, 1)
        assert honest_passed is False

        def always_pass(*_args: Any, **_kwargs: Any) -> tuple[bool, str]:
            return True, "ok"

        mutant_passed, _ = always_pass(0, _WRONG_RESULT_OUTPUT, _CASE_EXPECTED, 1, 1)
        assert mutant_passed != honest_passed, "always-pass mutant was not killed"

    def test_ignored_assertion_mutant_flips_the_verdict(self) -> None:
        """M-ignored-assertion: exit-code and envelope are checked but the
        result/expected comparison is dropped.

        Killed: a wrong observed result must not pass.
        """

        def ignore_assertion(
            exit_code: int, output: str, expected: Any, index: int, total: int
        ) -> tuple[bool, str]:
            if exit_code != 0:
                return False, "exit"
            if '"ok": true' not in output:
                return False, "envelope"
            return True, "ok"  # comparison skipped — the mutation

        honest_passed, _ = _grade_case(0, _WRONG_RESULT_OUTPUT, _CASE_EXPECTED, 1, 1)
        mutant_passed, _ = ignore_assertion(0, _WRONG_RESULT_OUTPUT, _CASE_EXPECTED, 1, 1)
        assert honest_passed is False
        assert mutant_passed != honest_passed, "ignored-assertion mutant was not killed"

    def test_spoofed_marker_mutant_flips_the_verdict(self) -> None:
        """M-marker-honoring: candidate-printed PASS counts as success.

        Killed: the #852 exploit response must stay a failure.
        """
        honest_passed, _ = _grade_case(0, "PASS\n", _CASE_EXPECTED, 1, 1)
        assert honest_passed is False

        def marker_honoring(
            exit_code: int, output: str, expected: Any, index: int, total: int
        ) -> tuple[bool, str]:
            if "PASS" in output:
                return True, "ok"
            return _grade_case(exit_code, output, expected, index, total)

        mutant_passed, _ = marker_honoring(0, "PASS\n", _CASE_EXPECTED, 1, 1)
        assert mutant_passed != honest_passed, "marker-honoring mutant was not killed"

    async def test_swebench_score_depends_on_the_real_grader(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """End-to-end: run_swebench must produce 0.0 for an unfixed buggy
        candidate through the real sandboxed grader, while an always-pass
        mutant of run_function_checks would produce 1.0 — so the mutation is
        observable at the benchmark boundary, not just the unit seam."""
        monkeypatch.setattr(
            swebench_module, "SWEBENCH_SAMPLES", [dict(swebench_module.SWEBENCH_SAMPLES[0])]
        )
        genome = make_genome()

        async def buggy_llm(messages: Any, **kwargs: Any) -> str:
            return f"```python\n{swebench_module.SWEBENCH_SAMPLES[0]['buggy_code']}\n```"

        honest = await swebench_module.run_swebench(genome, buggy_llm)
        assert honest.score == 0.0

        async def always_pass(
            code: str, function_name: str, cases: list[Any], *, timeout: float = 10.0
        ) -> tuple[bool, str]:
            return True, "ok"

        monkeypatch.setattr(swebench_module, "run_function_checks", always_pass)
        mutated = await swebench_module.run_swebench(genome, buggy_llm)
        assert mutated.score == 1.0
        assert mutated.score != honest.score, "always-pass mutant was not killed"


# ---------------------------------------------------------------------------
# IFEval predicate mutants
# ---------------------------------------------------------------------------


class TestIfevalPredicateMutantsKilled:
    def test_inverted_predicate_mutant_flips_the_verdict(self) -> None:
        """M-inverted: _evaluate_rule returns 1.0 - score.

        Killed: bidirectional predicate tests — an inverted 'contains' turns
        a failing response into a passing one.
        """
        rule = {"type": "contains", "value": "solar"}
        assert _evaluate_rule("no keywords here", rule) == 0.0
        assert _evaluate_rule("solar power", rule) == 1.0
        inverted = 1.0 - _evaluate_rule("no keywords here", rule)
        assert inverted == 1.0, "inverted-predicate mutant was not killed"

    def test_permissive_unknown_rule_mutant_flips_the_verdict(self) -> None:
        """M-permissive-parser: unknown rule types award 0.5.

        Killed: unknown rules must contribute 0.0, so a sample containing one
        cannot approach a gate on that rule alone.
        """
        honest = _evaluate_rule("anything", {"type": "no_such_rule"})
        assert honest == 0.0
        permissive = 0.5  # the historical default
        assert permissive != honest, "permissive-parser mutant was not killed"

    @pytest.mark.asyncio
    async def test_run_ifeval_score_is_sensitive_to_predicates(self) -> None:
        """The adapter's aggregate must flow through the strict predicates:
        a failing response scores low honestly, and an always-1.0 predicate
        mutant would score exactly 1.0."""
        genome = make_genome()

        async def bad_llm(messages: Any, **kwargs: Any) -> str:
            return "x"  # fails nearly every sample's rules

        honest = await run_ifeval(genome, bad_llm)
        assert honest.score < 1.0

        always_one = 1.0  # mutant predicate output
        assert always_one != honest.score, "predicate mutant was not killed"


# ---------------------------------------------------------------------------
# Judge parser mutants (GAIA hard-gate evidence, #852 acceptance)
# ---------------------------------------------------------------------------


class TestJudgeParserMutantsKilled:
    def test_positive_floor_mutant_changes_malformed_verdict(self) -> None:
        """M-floor: judge_score falls back to 0.3 for malformed output.

        Killed: malformed output must be 0.0; the floor mutant is detectable
        and was exactly gate-height for GAIA (0.3 vs the 0.30 threshold).
        """
        assert judge_score("garbage") == 0.0
        floor_mutant = 0.3
        assert floor_mutant != judge_score("garbage"), "floor mutant was not killed"

    def test_substring_positive_word_mutant_changes_negated_verdict(self) -> None:
        """M-substring: 'correct' in text (checked before 'incorrect').

        Killed: 'incorrect' must score 0.0, not 0.8.
        """
        assert judge_score("incorrect") == 0.0
        substring_mutant = 0.8
        assert substring_mutant != judge_score("incorrect"), "substring mutant was not killed"

    @pytest.mark.asyncio
    async def test_empty_body_candidate_cannot_clear_the_hard_gate(self) -> None:
        """#852 acceptance: a candidate whose judge interactions produce
        garbage cannot enter the fitness pool through scorer defaults.

        The GAIA adapter awards max(exact, judged); with the judge parser
        failing closed, a constant non-answer response scores 0.0 on every
        sample except the documented single-letter substring tier (gaia_13's
        expected answer is 'A'), for 0.06 aggregate — far below the 0.30
        hard gate, which therefore rejects the genome. Under the historical
        0.3 judge floor the same candidate scored exactly 0.30 and passed.
        """
        genome = make_genome()

        async def garbage_judge_llm(messages: Any, **kwargs: Any) -> str:
            # The pipeline under test answers everything with text that is
            # neither the answer nor a parseable judge verdict.
            return "I have disabled my implementation bodies."

        result = await run_gaia(genome, garbage_judge_llm)
        assert result.score < 0.30  # below the tuned proxy_gaia gate

        gated = make_genome()
        gated.eval_scores = {"proxy_gaia": result.score}
        passed, failures = _check_hard_gate(gated)
        assert passed is False
        assert any("proxy_gaia" in failure for failure in failures)

        # The historical floor would have cleared the same gate exactly.
        assert 0.3 >= 0.30  # documents the old exploit height


# ---------------------------------------------------------------------------
# tau-bench prose-mention mutants
# ---------------------------------------------------------------------------


class TestTauProseMentionMutantsKilled:
    def test_prose_mention_mutant_flips_the_verdict(self) -> None:
        """M-mention: re-introducing 'tool name appears in prose' as a call.

        Killed: negation prose must score 0.0; the mention mutant is
        detectable.
        """
        sample = {
            "expected_tool_calls": ["refund_order"],
            "tools": [{"name": "refund_order"}],
        }
        response = "I cannot invoke refund_order for you."
        assert _score_tool_usage(response, sample) == 0.0

        def mention_mutant(response: str, sample: dict[str, Any]) -> float:
            mentioned = [
                t["name"] for t in sample["tools"] if t["name"].lower() in response.lower()
            ]
            return 1.0 if mentioned else 0.0

        assert mention_mutant(response, sample) == 1.0
        assert mention_mutant(response, sample) != _score_tool_usage(response, sample), (
            "prose-mention mutant was not killed"
        )


# ---------------------------------------------------------------------------
# Metadata-leak mutants (#852 criterion: no rubric through reflection)
# ---------------------------------------------------------------------------


class TestMetadataLeakMutantsKilled:
    def test_redaction_mutant_is_detectable(self) -> None:
        """M-leak: _failed_rule_descriptions echoes rule values again.

        Killed: the redacted description must not contain the literal value.
        """
        from maistro_evolve.benchmarks.ifeval import _failed_rule_descriptions

        rules = [{"type": "contains", "value": "secret-keyword"}]
        descriptions = _failed_rule_descriptions("nothing matches", rules)
        assert descriptions == ["contains=<redacted>"]
        leak_mutant = [f"contains={'secret-keyword'!r}"]
        assert "secret-keyword" not in "; ".join(descriptions)
        assert leak_mutant != descriptions, "metadata-leak mutant was not killed"

    @pytest.mark.asyncio
    async def test_swebench_failure_metadata_never_contains_hidden_expected_values(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """#852: the hidden-case rubric must not reach reflection metadata."""
        monkeypatch.setattr(
            swebench_module, "SWEBENCH_SAMPLES", [dict(swebench_module.SWEBENCH_SAMPLES[0])]
        )
        genome = make_genome()

        async def buggy_llm(messages: Any, **kwargs: Any) -> str:
            return f"```python\n{swebench_module.SWEBENCH_SAMPLES[0]['buggy_code']}\n```"

        result = await swebench_module.run_swebench(genome, buggy_llm)

        assert result.score == 0.0
        assert result.metadata["failures"], "a failing run must record a failure entry"
        serialized = repr(result.metadata["failures"])
        assert str(_CASE_EXPECTED) not in serialized
        assert "[1, 2, 3, 4, 5]" not in serialized
        assert "expected" not in serialized.lower()
