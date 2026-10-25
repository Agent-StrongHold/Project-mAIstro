---
inventory-delta:
  tests/: +54
---
# #1629: acceptance-based repository delivery planner

Suite: `tests/`
Delta: +54 collected cases in `tests/test_plan_delivery.py`; no existing tests
removed, renamed, skipped or weakened. No baseline or workflow change.

The cases execute the real planner and CLI over deterministic reviewed-snapshot
fixtures. They cover partial/document-only completion, exact-SHA and independent
review metadata, duplicate/conflicting proof, current-head and freshness guards,
closed-state reconciliation, missing dependencies/cycles, path/interface
conflicts, existing-owner reuse, inactive ownership reservations, WIP, complete
census requirements, deterministic priority and malformed/duplicate JSON.

Local validation: 54 passed, zero skipped. Branch coverage of the planner reports
99% combined coverage; the only unexecuted source line is its `__main__` exit.
This is isolated local validation, not a full locked-monorepo or PG proof.
Exact-head repository CI and independent review remain required.

The follow-up CHANGELOG Unreleased/Added entry for the read-only
delivery-planning command, linked to #1629, is now present in the root
CHANGELOG (added from a complete checkout; the file was not replaced from a
partial fetch). No release completion is claimed by this note.
