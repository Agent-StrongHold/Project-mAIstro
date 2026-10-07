---
inventory-delta:
  packages/maistro-core/tests: +27
  packages/hive-conductor/backend/tests: +3
---

# Issue 1058 CI repair: gate-trueing simplification of the HITL evidence seam

The three red CI gates at 9da165eff were repaired by making the code
simpler and more directly tested, not by re-banking debt:

- **exact-debt-ledger (vulture)**: the factory-token seam
  (`_authenticated_session_from_verified_boundary`,
  `HitlAuthorization.for_verified_session`, `for_delegated_service`) had no
  in-scope consumer, so the scan reported three new unused identities. The
  factories are removed: `HitlAuthorization.__init__` now runs the entire
  evidence validation itself (typed delegation evidence, subject binding,
  Workspace coverage, validator/consumer presence, non-blank claims), so no
  construction path can bypass it.
- **Quality gate (radon)**: `answer_record` (C 14, baseline 11) and the two
  evidence `__post_init__` blocks (C 13/C 11) were decomposed
  (`_answerable_moment`, `_require_claim_*`, `_bind_delegation_evidence`,
  `_sorted_due_records`, shared in-memory `_mutate_authorized_hitl`). The
  now-stale `answer_record` baseline entry is pruned as the gate itself
  demands on improvement.
- **Coverage gate (diff coverage)**: the branch's own security-relevant
  denial arms were never exercised — evidence validation raises, `permits()`
  denials (expired/unvalidated/raising validator), backend guard arms
  (`require_hitl_authorization`, `limit<=0`), SQLite due-index widening past
  denied candidates, canonical deny/mismatch paths, the stale-pause-entry
  arm of `/pending`, inspect no-match, and the workspace authority's
  fail-closed view guards.

maistro-core additions (test_hitl_settlement.py): parametrized
authorization/delegation-evidence fail-closed construction, typed-evidence
TypeError, `require_hitl_authorization(None)`, `permits()` denial paths,
per-backend due-listing guards, unscoped expiry tick, machine-wait answer
refusal, canonical deny/mismatch, SQLite denied-candidate paging, and an
unscoped-page double proving `expire_hitl_pauses` re-filters candidate pages.

hive-conductor additions: a stale pause entry neither listed nor inspectable
(test_hitl_door.py); view-compose fail-closed member writes and projection-row
deletion (test_workspace_authority.py).
