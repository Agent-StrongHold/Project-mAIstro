---
inventory-delta:
  tests/: +3
---
# claude-ws-459-strict-m1-closeout-mode-and-a-named-pari-b993

#459 adds strict M1-closeout mode to `tests/cross_product_parity/harness.py`:
`dependency_assessment` now raises `DependencyUnavailable` instead of
returning a named blocker when `MAISTRO_PARITY_STRICT=1`. Two new tests in
`tests/cross_product_parity/test_cross_product_parity.py` cover it end to
end with a synthetic `Dependency`/`SourceProbe` pointed at a path that does
not exist:

- `test_strict_mode_turns_synthetic_unavailable_dependency_into_a_failure`
  proves strict mode raises.
- `test_non_strict_mode_still_reports_named_blockers` proves development
  mode is unchanged: the same unavailable dependency still comes back as a
  named blocker rather than failing.

A Codex review of PR #1641 then caught a real gap this opened: once a named
product dependency (e.g. `CONDUCTOR_INSPECTION`, `GOLDEN_BASELINES`) lands,
scenarios 1/2/3/6 in `test_cross_product_parity.py` fall through to
assertions that only check import/source tokens (or, for scenario 6, feed
the golden fixture's own example back at itself) rather than a real
cross-product execution — so strict mode could read that as closure
evidence once #1036 lands, even though nothing real executed.
`harness.py` now adds four permanently-evidenced blockers
(`REAL_BUILDERS_CONDUCTOR_SCENARIO`, `REAL_SCHEDULE_CONDUCTOR_SCENARIO`,
`REAL_EVOLVE_CONDUCTOR_SCENARIO`, `REAL_GOLDEN_PRODUCT_OBSERVATION`), each
probing for a marker/rewrite that only exists once the scaffold is replaced
with a real execution, and each scenario's `dependency_assessment` call now
includes its own. `test_scaffold_only_scenarios_stay_blocked_until_real_execution_lands`
proves all four stay unavailable today, and specifically that
`REAL_GOLDEN_PRODUCT_OBSERVATION` is the only thing keeping scenario 6 from
reading as closure evidence even though `GOLDEN_BASELINES` itself is
already satisfied on this branch.

No other suite's collection changed.
