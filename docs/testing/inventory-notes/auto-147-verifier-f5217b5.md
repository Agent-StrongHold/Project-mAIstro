# auto-147 independent verification at develop-merge head f5217b50e

Verifier re-derivation of #147 acceptance at `f5217b50e9ed55548e8a2e0ce0d3e65effb53945`
(merge of develop `84402748f` into `auto-147`; base = `84402748f`, merge-base confirmed).
All evidence below was executed by the verifier at this exact head on a clean tree. The
prior round's evidence (head `1c3434dbc` -> note commit `25d90bba9`) was rejected by the
driver as `worktree_changed`; this round every measurement ran BEFORE the only tree
change, which is this note's own commit.

## Issue acceptance — re-proven by execution at this head

- 62 passed: `test_agent_delegate_remote.py` + `test_agent_delegate_remote_child_run.py`
  + `test_agent_delegate_remote_review.py`. Named acceptance nodes PASSED at this head:
  in-process child Run parented to Run+NodeRun (`parent_run_id`/`parent_node_run_id`
  asserted, filed in the parent's Workspace/Project); cross-instance child Run including
  the real-HTTP `GuestPeerManager` seam; provenance naming `admission_source`/mode/both
  agents/`a2a_task_id` receipt; both escape guards firing (`TestTheEscapeGuardsFire` —
  `RunIntegrityError` "Workspace" / "Project boundaries", via the shared
  `validate_child_scope`, `runs/store.py:209/231/233`); resolver wiring
  (`TestTheResolverWiresTheNode`; production path `container.py:1856-1857` builds
  `A2ADelegator()`/`GuestPeerManager()`, `:872-884` feeds them plus `run_store` into
  `build_node_resolver`, authority-driven `compose_node`, `graph/nodes/__init__.py:122`);
  both missing-dependency paths raise `DelegationNotConfiguredError` (never a returned
  `status="failed"` shaped like a peer refusal).
- 146 passed: `agents/test_factory.py`, `graph/durable_runs/test_answer_gated_recovery.py`,
  `graph/durable_runs/test_pause_reason_wakers.py`, `runs/test_human_pause_reasons.py`,
  `runs/test_task_kinds.py` (pause metadata carries `run_id`; `DelegateRemoteOut.run_id`).
- Full `packages/maistro-core/tests` in CI shape (pg18 + `alembic upgrade head`):
  10903 passed / 46 skipped / 1 xfailed, plus the one sequencing test
  `test_an_unmigrated_database_names_the_command_that_fixes_it` — it fails only against an
  already-migrated DB and was verified PASSING against a fresh unmigrated database.
  Totals match the recorded suite inventory (10951).
- hive-conductor: `test_maistro_core_adapter.py` 9 passed; `test_dag_agents.py` 15 passed.
- `ruff check .` / `ruff format --check .` clean; `mypy` over all six package src trees
  clean (715 files, with `--extra bootstrap` synced); both suite inventories match;
  `check-reachability.py`, `check-credential-authority.py`, `check-wiring-reads.py`,
  `verify-monorepo-layout.sh`: all exit 0.

## Required ac-state gate — green in CI shape at this head, against the new base

`check-ac-state.py --run-tests --ratchet --mandate 84402748f...` (fresh pg18 container,
`alembic upgrade head` first, per `quality.yml:940-955`) exited 0 at this head: design
coverage measured 38.0924%, exactly the banked bound (`auto-147.json`); ratchet folded
from the 73 notes at base `84402748f`; acceptance mandate 0 unproven; chain mandate OK;
`'Implemented', contradicted: 0`.

Diagnostic note: the same gate WITHOUT `MAISTRO_TEST_PG_DSN` fails with coverage 33.0728
< floors 33.9095/38.0924 — 133 ac-marked tests skip (110 core + 5 conductor + 18 root),
all gated on `MAISTRO_TEST_PG_DSN`, and the passing rung reads skips as no evidence.
Environment-only; CI's `quality-gate` job always has the service. The gate also wrote
nothing tracked (`quality/ac-state.json` is gitignored).

## Prior findings — disposition at this head

- Receipt/Attempt identity (ADR-082526-7f02): resolved. Reservation Attempts record
  `{"mode": ...}` only — no `task_id: ""` placeholder (`_yield_transport_attempt`);
  the settling Attempt carries the receipt in its evidence, and only when the answer
  carries one; Run provenance receives `a2a_task_id` once, post-acceptance, via
  `attach_delegation_receipt` (conflicting re-attach raises `RunIntegrityError`), which is
  what #147's own acceptance asks the child Run's provenance to name. The ADR bars
  retro-writing *admission* provenance; dispatch identity stays on the Attempt.
  `TestTheReceiptIsAttemptOwnedIdentity` 3/3 PASSED at this head.
- AC-state note deletions vs develop: the required gate itself passes at this head in CI
  shape (above), with `'Implemented', contradicted: 0` — the earlier "4 contradicted
  Implemented specs" observation does not reproduce at this head. The deletions are the
  sanctioned fold-maintenance surface (`ac_state_notes` fold reads base notes; gate exit 0
  is the arbiter).
- PR #1291 body ("Draft auto-opened ... Refs #147 ...") and every commit subject/body in
  `84402748f..f5217b50e`: no `fixes/closes/resolves` closure keywords. No issue-closure
  action performed. GitHub CI rollup: not available in the snapshot — remains UNVERIFIED;
  the required gates were instead executed locally by the verifier at this head.
