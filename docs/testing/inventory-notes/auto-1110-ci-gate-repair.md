---
inventory-delta:
  packages/hive-conductor/backend/tests: +9
  packages/maistro-core/tests: +1
---
# auto-1110-ci-gate-repair

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

CI-repair round for #1110 at head `85e5a2437b`. The two red required checks
were reproduced locally and repaired with evidence, not scanner guesses:

* **Coverage gate (diff coverage).** `check-diff-coverage.py` against base
  `ca4caec7d` failed per-file: `maistro/graph/durable_runs/hitl.py` at 80% of
  changed lines (the new `project_ids` filter's `continue` was never executed)
  and `services/hitl_authorization.py` at 85.9% (store-level refusal paths
  only reachable outside the HTTP fixtures). Fixed by adding the tests below —
  one core settlement test that scopes an expiry tick to one Project's
  `project_ids`, and nine service-level refusal tests (non-member, foreign
  Workspace Project, raising store read, foreign-Workspace membership row,
  unknown permission, missing store, rootless Workspace, denied vs authorized
  explicit `project_id`). After the additions the gate reports every measured
  file at or above 90/80, re-verified against combined core+hive coverage
  data.
* **Quality gate (acceptance-state ratchet).** `check-ac-state.py
  --run-tests --ratchet --mandate` failed on a develop-inherited condition:
  the `design_coverage@33.9095` grant in `quality/ratchet-authorizations.json`
  had been independently overtaken by three landed notes (`auto-1138.json`,
  `auto-1158.json`, `auto-48.json`), and the checker itself prescribed pruning
  it. Pruned exactly that entry; the floor stays held by the notes and the
  gate re-runs green with `RATCHET_BASE_REV=origin/develop` and PostgreSQL.
  This edit is a CI-repair-round ledger amendment prescribed by the failing
  gate's own output, not a floor weakening: design coverage measures 38.09%.

Test movement: `packages/maistro-core/tests` +1
 (`test_expiry_settles_only_projects_the_caller_holds_authority_over` in
 `graph/durable_runs/test_hitl_settlement.py`); `packages/hive-conductor/
backend/tests` +9 (new `test_hitl_authorization_service.py`). No tests were
removed or renamed, so the deltas are pure additions.
