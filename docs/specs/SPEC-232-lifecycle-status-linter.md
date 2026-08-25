---
id: SPEC-232
title: "Lifecycle status linter: tools/lint_lifecycle.py"
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-06-20
substrate: []
implements:
  - maistro-engine#ADR-097
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests:
  - tests/tools/test_lint_lifecycle.py
layer: Governance
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-232: Lifecycle status linter

## Context

ADR-097 defines a forward-only lifecycle state machine for ADR/spec `status` values,
required fields per status, a `history` audit trail, and an AC-ID-to-test
traceability convention (`@pytest.mark.ac("SPEC-NNN/AC-N")`). `tools/lint_lifecycle.py`
implements the linter side of this; this SPEC documents what it actually checks today,
including the parts of the ADR's enforcement list it does not yet cover.

## Goals

- Document the linter's actual checks against the ADR's enumerated enforcement list.
- Document adoption of the `@pytest.mark.ac` convention elsewhere in the repo.
- Flag that the linter is not yet wired into CI.

## Non-goals

- Adding CI wiring for the linter (tracked as an open question).
- Adding the cross-reference checks (child-spec status gating) the linter doesn't yet have.

## Decision

`/home/user/maistro-engine/tools/lint_lifecycle.py` (315 lines) implements:

- **Status validity per kind** — separate `ADR_STATUSES` (8 values) and
  `SPEC_STATUSES` (9 values) lists, checked against each document's `kind`.
- **Required fields per status** — `ADR_REQUIRED`/`SPEC_REQUIRED` dicts, e.g.
  `Fully Specced` requires `title, created, owners, implements`; `Superseded`
  requires `superseded-by`.
- **Forward-only history order** — `lint_history()` computes a transitive closure
  (`reachable_from`) over `ADR_TRANSITIONS`/`SPEC_TRANSITIONS` and flags any `history`
  entry not reachable from the previous one; also checks the last `history` entry
  matches the document's current `status`.
- **AC-ID traceability** — `check_ac_traceability()`: for specs at `Tests Passing` or
  `Implemented`, extracts `**AC-N**` IDs from the `## Acceptance Criteria` section and
  confirms a matching `@pytest.mark.ac("SPEC-NNN/AC-N")` exists under the configured
  test roots.

Not yet implemented, per the ADR's own enforcement list:

- **Date consistency** between status-field dates and `history` entry dates — the
  linter checks ordering of statuses, not that, e.g., an `accepted:` field date
  matches the corresponding `history` entry's date.
- **Cross-reference checks** for `Fully Specced`/`Implemented` ADRs requiring their
  child specs to be at a minimum status — the linter only enforces that `implements`
  is non-empty for `Fully Specced` ADRs; it does not look up child specs' actual
  status.

The `@pytest.mark.ac` convention is adopted in practice:
`packages/maistro-core/tests/tasks/test_progress_webhook.py`,
`packages/maistro-bootstrap/tests/test_plan.py`, `test_builders_sandbox.py`,
`packages/hive-conductor/backend/tests/test_api.py` (e.g.
`@pytest.mark.ac("SPEC-175/AC-2")`, `@pytest.mark.ac("SPEC-201/AC-9")`).

No CI workflow currently invokes `lint_lifecycle.py` (no match for `lint_lifecycle`
across `.github/workflows/*.yml`), and no dedicated test suite exists for the linter
itself.

## Acceptance criteria

- [x] Linter validates `status` is a valid value for the document's `kind`
- [x] Linter validates required fields are present per current status
- [x] Linter validates `history` entries are forward-only (no backward transitions) and the latest entry matches current `status`
- [x] Linter implements AC-ID-to-test traceability checking via `@pytest.mark.ac`
- [x] `@pytest.mark.ac` convention is adopted in at least 4 test files across packages
- [ ] Linter validates date-field consistency with `history` entry dates
- [ ] Linter validates cross-reference status gating (ADR `Fully Specced`/`Implemented` requiring child specs at minimum statuses)
- [ ] Linter runs as a CI pre-merge gate
- [ ] Linter has its own dedicated test suite

## Testing

No dedicated test suite for `tools/lint_lifecycle.py` exists yet
(`packages/maistro-registry`'s `FrontMatter`/`Status` model has separate unit tests,
but those cover the registry's own schema validation, not this linter script). The
AC-ID traceability mechanism it enforces is itself exercised indirectly by the
`@pytest.mark.ac`-decorated tests listed above.

## Open questions

- Should `lint_lifecycle.py` be wired into `.github/workflows/registry.yml` (or a new
  workflow) as a pre-merge gate, per ADR-097's "linter runs in CI as a pre-merge
  gate"? Currently it does not.
- Should date-consistency and cross-reference checks be added in a follow-up, and
  should that follow-up get its own test suite under e.g. `tests/tools/`?
- The ADR-097 migration plan calls for a backfill PR (history fields from git dates,
  re-classification of mismatched statuses, 2-week warning period before blocking) —
  has that backfill happened? Not verified in this audit.

## References

- `tools/lint_lifecycle.py`
- `docs/adr/ADR-097-lifecycle-status-machine.md`
- `packages/maistro-core/tests/tasks/test_progress_webhook.py`
- `packages/maistro-bootstrap/tests/test_plan.py`
- `packages/hive-conductor/backend/tests/test_api.py`
