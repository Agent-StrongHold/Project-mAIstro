---
inventory-delta:
  packages/maistro-core/tests: +0
---
# auto-147 repair-phase re-check at head 7de733072

Focused validation of #147 acceptance executed at `7de73307200a67a059c4e3ab6d9ae8cc4e7b81f2`
with a live Postgres (`auto-147-pg` pg18 container, DSN via `MAISTRO_TEST_PG_DSN`,
`alembic_version` at head `036_audit_log_org_scope` — the true tip of the numeric lineage,
which `040` extends). No production code changed in this pass; the one tree edit is the
inventory-ledger repair recorded below.

## Acceptance — re-proven by execution at this head

- Delegation suites: `test_agent_delegate_remote.py` + `test_agent_delegate_remote_child_run.py`
  + `test_agent_delegate_remote_review.py` + `test_container_delegation_wiring.py`
  — **67 passed**. This includes, by name: in-process child Run
  (`test_an_in_process_delegation_creates_a_child_of_the_delegating_node_run`), cross-instance
  child Run (incl. the real-HTTP `MockTransport` variant), provenance naming
  task/mode/both agents/`a2a_task_id` receipt, both escape guards firing
  (`RunIntegrityError` via the store's own `validate_child_scope`), resolver wiring
  (`test_build_node_resolver_supplies_the_delegate_nodes_dependencies`), both
  `DelegationNotConfiguredError` loud refusals, and the Attempt-owned receipt pins
  (`test_the_reservation_attempt_records_no_receipt_placeholder`,
  `test_the_settling_attempt_names_the_transport_receipt`,
  `test_the_pause_payload_supplies_the_run_id`).
- Changed-package suite with PG: `uv run pytest packages/maistro-core/tests -q`
  — **10673 passed, 116 skipped, 1 xfailed**. graph/runs scoped re-runs: 1485 passed /
  1062 passed. Hive `test_dag_agents.py`: 13 passed. Waker suite
  (`test_pause_reason_wakers.py`): 34 passed.
- `uv run ruff check .` clean; `ruff format --check .` clean (2528 files);
  six-package `mypy` clean (712 files).
- `uv run python scripts/check-ac-state.py --run-tests --ratchet --mandate 750edd84d`
  with the DSN exported: **EXIT 0**; design coverage measured **37.693**, exactly on the
  banked floor (`quality/ac-state-notes/auto-147.json`); acceptance and chain mandates both
  OK. This reproduces the prior claim that the earlier 33.03% reading was a PG-less
  measurement, and closes prior finding 2 at this head.
- Prior finding 1 (receipt placeholder vs ADR-082526-7f02) does not reproduce at this head:
  the reservation Attempt records `{"mode": ...}` only, the settling Attempt carries the
  receipt, and Run provenance receives `a2a_task_id` once via `attach_delegation_receipt`
  (conflict-guarded, store.py `RunIntegrityError` on a second receipt) — which is the field
  #147's own acceptance requires the provenance to name.

## Repair recorded by this note: a double-counted inventory delta

`check-suite-inventory.py` FAILED at this head: `packages/maistro-core/tests` expected
10791, collected 10790 (13-suite gate EXIT 1). Cause: commit `7de733072` added exactly one
collected test (the positive `answer_record` pin; waker file went 33 -> 34 collected nodes)
but recorded the +1 **twice** — `auto-147-6ac7.md` was bumped +11 -> +12 *and* the new
`auto-147-merge-pause-wakers.md` claimed the same +1. Arithmetic proof: at the merge parent
`750edd84d` the ledger was consistent (base 7690 + deltas = 10789 = collected 10789, i.e.
10790 minus the one test added later); one collected test plus two delta units is exactly
the observed -1. Fix: `auto-147-6ac7.md` returns to +11 (the merge repair's +1 stays owned
by `auto-147-merge-pause-wakers.md`, which describes that change); prose adjusted
accordingly. After the repair the gate reports **13/13 suites match, EXIT 0**.

## Scratch salvage (not part of the branch)

Five untracked ad-hoc scripts at the repo root
(`test_delegate_child_run*.py`, `test_delegate_resolver.py`) — print-based exploration
duplicating assertions already committed in `test_agent_delegate_remote_child_run.py` —
broke both ruff gates locally. They were preserved byte-identical (md5-verified) to the job
directory `scratch-salvage/` and removed from the worktree; the tracked tree was and remains
untouched by this.
