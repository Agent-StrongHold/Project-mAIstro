---
inventory-delta:
  packages/maistro-evolve/tests: +33
---
# Issue #852 anchored judge parsing and bidirectional IFEval predicates

Rewrites `judge_score` in `benchmarks/scoring.py` under a fail-closed,
anchored policy: the demanded bare-number format (used by every in-repo judge
prompt) is now parseable; positive/negative verdict words match whole-word
only with negative-first ordering (`judge_score("incorrect")` was 0.8 via
substring match, now 0.0); JSON-object responses are schema-or-failure; and
missing/malformed output returns 0.0 instead of a 0.3 floor that exactly met
GAIA's 0.30 fitness hard gate.

`json_field_match` becomes bidirectional: a missing field scores 0.0 (the
historical hardcoded `expected=None` rewarded the field being absent), and an
explicit expected value is enforced when a rule provides one.

`benchmarks/ifeval.py`: `json_field` rules use the new presence/value
contract; unknown rule types score 0.0 instead of a permissive 0.5; and
failure metadata redacts literal rule values (type and structural field names
are kept) so the optimizer reflection loop no longer receives the rubric.

Test deltas:

- `tests/test_scoring.py`: TestJudgeScore rewritten to the adversarial
  contract (negation, bare numbers, malformed input, JSON schema, clamping)
  plus TestJsonFieldMatchBidirectional (+33 tests total across both files).
- `tests/benchmarks/test_ifeval.py` (new): bidirectional rule evaluation,
  fail-closed unknown rules, and mutation-killing assertions for value
  redaction and permissive-parser regressions.

No existing test was deleted; the two pre-existing yes/no boundary tests were
updated from the removed 0.3 neutral floor to the new 0.0 fail-closed
expectation.
