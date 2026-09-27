---
inventory-delta:
  tests/: +2
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

No other suite's collection changed.
