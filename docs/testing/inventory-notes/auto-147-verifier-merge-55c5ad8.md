# auto-147 independent verification at merge head 1c3434dbc

Verifier re-derivation of #147 acceptance at `1c3434dbc7cd2b4954b7e99cf4d3084858989173`
(merge of develop `55c5ad892` into `auto-147`, plus `93ec7df9f` #364 answer-auth test fix).
All evidence below was executed by the verifier at this exact head; nothing inherited.

## Issue acceptance — proven by execution

- 139 passed: `test_agent_delegate_remote.py`, `test_agent_delegate_remote_child_run.py`,
  `test_agent_delegate_remote_review.py`, `test_container_delegation_wiring.py`,
  `test_node_composition.py`, `test_container_node_composition.py`. All named acceptance
  nodes PASSED: in-process child Run parented to Run+NodeRun; cross-instance child Run
  (incl. the real-HTTP `MockTransport` seam through `GuestPeerManager`); provenance naming
  `admission_source`/mode/both agents/`a2a_task_id` receipt; both escape guards
  (`TestTheEscapeGuardsFire`, `RunIntegrityError` "Workspace" / "Project boundaries" via
  `validate_child_scope` — the same guard `create_run` enforces, `runs/store.py:209/733`);
  resolver wiring (`TestTheResolverWiresTheNode`); both `DelegationNotConfiguredError`
  loud refusals with `error_code` set (never a returned `status="failed"` shaped like a
  peer refusal).
- 664 passed / 39 skipped: `test_task_kinds.py`, `test_human_pause_reasons.py`
  (`awaiting_remote_delegation` now a human-owned, answer-gated pause),
  `agents/test_factory.py`, `agents/test_delegation.py`,
  `agents/test_actor_requested_delegation.py`, all of `graph/durable_runs/` (incl. the
  durable parent pause -> server-stamped answer -> resume -> child settle path).
- hive-conductor: `test_maistro_core_adapter.py` 9 passed; `test_dag_agents.py` 15 passed
  (ADR-082526-3ca6 AC-4/AC-5 call-time resolver wiring with the container's
  `a2a_delegator`).
- `ruff check .` / `ruff format --check .` clean; `mypy packages/maistro-core/src` clean
  (629 files) after `uv sync --extra bootstrap` (the 5 import-not-found errors without the
  extra are env-only, in untouched `cli/_builders_tui.py`/`cli/_install.py`).
- `check-suite-inventory.py` for `packages/maistro-core/tests` and
  `packages/hive-conductor/backend/tests`: both match the recorded inventory.
- Workflow gates at this head: `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` (the canonical quality.yml:810 shape) exit 0,
  1414 -> 1413 reviewed identities (the branch pruned exactly the now-used
  `a2a/delegate.py::register_agent_capability` allowance); `check-reachability.py`,
  `check-credential-authority.py`, `check-wiring-reads.py` (vs base `55c5ad892`),
  `verify-monorepo-layout.sh`: all exit 0.

## Required ac-state gate — green in CI shape, executed at this head

`uv run python scripts/check-ac-state.py --run-tests --ratchet --mandate 55c5ad892...`
(pg18 container, `alembic upgrade head` first, per `quality.yml:940-955`) exited 0:
design coverage measured 38.0924%, exactly the banked bound
(`quality/ac-state-notes/auto-147.json`); ratchet folded from the 73 base notes;
acceptance mandate 0 unproven; chain mandate OK; `'Implemented', contradicted: 0`.

## Prior findings — disposition at this head

- Receipt placeholder (ADR-082526-7f02): repaired at ancestor `dc408b0fe`, pinned by
  `TestTheReceiptIsAttemptOwnedIdentity` (3 PASSED). Reservation Attempt records
  `{"mode": ...}` only — no `task_id: ""`; the settling Attempt carries the receipt under
  the same key the answer uses; Run provenance receives `a2a_task_id` once, post-acceptance,
  via `attach_delegation_receipt`, which is what #147's acceptance asks the provenance to
  name. No ADR conflict: ADR-082526-7f02 bars rewriting *admission* provenance; the receipt
  is not admission provenance and dispatch identity stays on the Attempt.
- AC-state note deletions from driver commit `1aa326b4b`: resolved as sanctioned pruning.
  The verifier recomputed the fold with the repo's own `scripts/ac_state_notes.py`:
  fold(base `55c5ad892`) vs fold(HEAD) — every debt counter identical, design coverage
  tightened 37.693 -> 38.0924 (no loosened counter). All 68 deleted notes are in
  `ac_state_notes.stale()` (dominated by the fold of the others); 4 stale notes were
  conservatively kept. `_baseline.json` moves are dominated or tightening. The required
  gate itself passes in CI shape at this head.
- PR #1291 body and every branch commit message: no `fixes/closes/resolves` closure
  keywords; the body says "Refs #147" only. No issue-closure action performed.
