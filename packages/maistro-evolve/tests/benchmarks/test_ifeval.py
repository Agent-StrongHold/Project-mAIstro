"""Adversarial tests for the proxy IFEval adapter's rule evaluation (#852).

Bidirectional coverage: a rule passes only when the required property is
actually present and correct, and fails when it is missing, wrong, or the
rule type is unknown. Also pins the redaction of literal rule values in
failure metadata that feeds the optimizer reflection loop.
"""

from __future__ import annotations

from maistro_evolve.benchmarks.ifeval import (
    _evaluate_rule,
    _failed_rule_descriptions,
    _score_response,
)
from maistro_evolve.benchmarks.scoring import json_field_match


class TestJsonFieldBidirectional:
    def test_required_present_passes(self) -> None:
        assert (
            _evaluate_rule('{"benefits": ["a", "b"]}', {"type": "json_field", "field": "benefits"})
            == 1.0
        )

    def test_missing_field_fails(self) -> None:
        # #852: the hardcoded expected=None rewarded exactly this response.
        assert _evaluate_rule('{"other": 1}', {"type": "json_field", "field": "benefits"}) == 0.0

    def test_empty_object_fails(self) -> None:
        assert _evaluate_rule("{}", {"type": "json_field", "field": "benefits"}) == 0.0

    def test_null_value_fails_presence_policy(self) -> None:
        assert (
            _evaluate_rule('{"benefits": null}', {"type": "json_field", "field": "benefits"}) == 0.0
        )

    def test_explicit_expected_value_enforced(self) -> None:
        rule = {"type": "json_field", "field": "answer", "value": 42}
        assert _evaluate_rule('{"answer": 42}', rule) == 1.0
        assert _evaluate_rule('{"answer": 43}', rule) == 0.0
        assert _evaluate_rule("{}", rule) == 0.0

    def test_scoring_helper_agrees(self) -> None:
        assert json_field_match('{"k": "v"}', "k") == 1.0
        assert json_field_match("{}", "k") == 0.0


class TestUnknownRuleFailsClosed:
    def test_unknown_rule_type_scores_zero(self) -> None:
        # #852: the old 0.5 default let an unrecognized rule satisfy gates
        # without any predicate being evaluated.
        assert _evaluate_rule("anything at all", {"type": "no_such_rule"}) == 0.0

    def test_permissive_mutation_would_flip_score(self) -> None:
        # Mutation killer: if _evaluate_rule were reverted to a permissive
        # default (>= 0.25), a sample with one unknown rule would clear a 0.2
        # gate on that rule alone. Pin the strict behavior from the adapter's
        # aggregate path too.
        assert _score_response("irrelevant", [{"type": "no_such_rule"}]) == 0.0


class TestFailureMetadataRedaction:
    def test_literal_rule_values_redacted(self) -> None:
        rules = [
            {"type": "contains", "value": "secret-keyword"},
            {"type": "json_field", "field": "benefits"},
        ]
        descriptions = _failed_rule_descriptions("no keywords here", rules)
        joined = "; ".join(descriptions)
        assert "secret-keyword" not in joined
        assert "contains=<redacted>" in joined
        # Structural field names stay (they are part of the task description).
        assert "benefits" in joined

    def test_passing_rules_not_reported(self) -> None:
        rules = [{"type": "contains", "value": "solar"}]
        assert _failed_rule_descriptions("solar power", rules) == []

    def test_mutation_leaking_values_is_killed(self) -> None:
        # If a regression re-exposes rule values, this catches it: the rule
        # fails (response contains the forbidden word) but the description
        # must not echo the literal value.
        rules = [{"type": "not_contains", "value": "evaporation"}]
        descriptions = _failed_rule_descriptions("evaporation happens", rules)
        assert descriptions == ["not_contains=<redacted>"]


class TestScoreResponseAggregation:
    def test_perfect_response_scores_full(self) -> None:
        rules = [{"type": "contains", "value": "solar"}]
        assert _score_response("solar energy", rules) == 1.0

    def test_empty_rules_vacuous_full_score_is_pinned(self) -> None:
        # Documented policy: no rules means nothing to violate. Samples in
        # the dataset always carry rules, so this cannot be exploited.
        assert _score_response("anything", []) == 1.0

    def test_partial_compliance_partial_score(self) -> None:
        rules = [{"type": "contains", "value": "solar"}, {"type": "contains", "value": "wind"}]
        assert _score_response("solar only", rules) == 0.5
