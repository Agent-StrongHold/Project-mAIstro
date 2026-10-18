---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/hive-conductor/backend/tests: +0
---

# Issue 1058 repair-lane re-validation at head e7efa32835dc

Documentation-only note. No production or test code changed; the prior verify
pass was rejected solely because its worktree changed during verification
(`worktree_changed`), so this pass re-executed the decisive checks at the
frozen head with the tree clean throughout.

## Executed at this head

- `uv run ruff check .` / `ruff format --check .` — clean.
- `uv run pytest packages/maistro-core/tests/graph/durable_runs/` — 472
  passed / 21 skipped.
- Backend HITL files (`test_hitl_door.py`, `test_hitl_timeout_cancel.py`,
  `test_registered_dag_recovery.py`, `test_workspace_authority.py`) — 48
  passed.
- Full backend suite `pytest packages/hive-conductor/backend/tests` —
  **2660 passed / 1 skipped / 0 failed**, closing the prior deterministic
  `submit_hitl_answer() missing keyword-only 'authorization'` finding.
- `check-suite-inventory` — ok for both `packages/hive-conductor/backend/tests`
  and `packages/maestro-core/tests`; `check-radon-baseline`,
  `check-doc-links`, `check-ac-state`, `check-retired-guidance` — exit 0.
- `mypy packages/maistro-core/src/maistro/graph/durable_runs/` — clean
  (17 files).
- Load-bearing pins re-run individually green: two-Workspace scoped
  list/inspect/answer/cancel + forged-`_pause` + unknown-404 +
  dags.write-scope arms, pending disclosure recheck, foreign expiry /
  late-race settlement, library membership/delegation pins.

## Literal mutation execution (acceptance: "mutation tests removing the Workspace membership predicate fail")

Both mutations were applied to the worktree, the pin was run to red, and the
file restored byte-identical (sha256 verified against HEAD; `git status`
clean after restoration):

1. `packages/maistro-core/src/maistro/graph/durable_runs/stores.py`
   `_mutate_authorized_hitl`: in-memory `permits(consume_evidence=True)`
   predicate replaced with `if False:` →
   `test_inmemory_mutations_refuse_a_foreign_workspace_authorization` FAILED.
2. `packages/hive-conductor/backend/routes/hitl.py` `list_pending_human_work`:
   per-record disclosure recheck replaced with `if False:` →
   `test_pending_rechecks_membership_before_disclosing_payload` FAILED.
