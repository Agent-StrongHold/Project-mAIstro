---
inventory-delta:
  packages/maistro-core/tests: +1
---
# docs-pre-v1-operating-standards-60a5

One new maistro-core node ID: `TestLearningDataclass::test_fields_round_trip_through_field_access`
in `packages/maistro-core/tests/memory/test_types_and_scopes.py`. It is the
evidence behind the `ADR-013/AC-7` criterion ("`Learning` dataclass round-trips
through field access"), which previously had no test constructing a `Learning`
with values and reading them back — only default-value assertions, which cannot
prove a round-trip.

The rest of this change moves no collected node ID. It decorates existing tests
with `@pytest.mark.ac("ADR-0NN/AC-M")` markers and adds `**AC-N**` ids plus
`tests:` / `ac-modules:` front matter to six memory ADRs (ADR-011, ADR-013,
ADR-014, ADR-015, ADR-016, ADR-017) that claim `status: Implemented`. The
decoration converts tests the suites already collected into acceptance-criteria
evidence for `scripts/check-ac-state.py`; collection is unchanged except for
the one new function above. Two existing assertions were strengthened in place
(`test_get_engine_success_returns_engine` now asserts `AsyncEngine`;
the ADR-016 reinforce/decay tests now also assert a new object is returned)
without adding or removing cases.
