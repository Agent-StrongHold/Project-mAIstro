---
inventory-delta:
  tests/: -1
---

# Develop-sync conflict resolution: one duplicate split-resolution parse test removed (L1836)

Resolving the preserved `origin/develop` (f956a8142) sync conflict in
`scripts/check-image-lock-reconciliation.py` + its tests: the branch had fixed
the beartype fork-collapse with **per-line** classification (run 40093845270),
develop had fixed the same bug independently with per-name version sets (run
40085096483, #1182 note). The resolution keeps the branch's per-line parser
(strictly stronger: a name with one unconditional and one marked line still
gates presence — develop's per-name rule would have lenient-gated the whole
name), adopts develop's `_expected_clause` mismatch rendering
(`!= one of a, b`), and unions both sides' tests.

The two suites had each added a parse-level test for the identical input and
assertions (`beartype==0.22.9 ; <'3.15'` + `beartype==0.23.1 ; >= '3.15'` →
required empty, both conditional): the branch's
`test_parse_expected_keeps_every_forked_version_of_a_name` and develop's
`test_parse_expected_keeps_every_version_of_a_split_resolution`. The merged
suite keeps develop's (its `SPLIT_EXPORT` constant is shared with the three
e2e split tests also adopted from develop) and drops the branch's duplicate:
**net −1** node ID in `tests/`.

No other count moved. Post-resolution evidence: merged suite 37/37 green;
run against develop's per-name parser, exactly the two per-line-classification
regressions fail (`test_parse_expected_classifies_unconditional_and_conditional_versions_by_line`,
`test_required_name_with_conditional_alternate_is_missing_only_when_absent`) —
the merged tests discriminate the semantics this resolution chose. The
mismatch-format assertions were updated to develop's `one of` rendering
(`test_version_outside_every_fork_is_a_mismatch`), which the shared helper now
produces.
