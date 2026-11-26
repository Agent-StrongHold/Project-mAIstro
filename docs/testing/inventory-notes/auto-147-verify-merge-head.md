# auto-147 independent verification at merge head a02a455574

Verifier re-derivation of #147 acceptance at `a02a455574908a735674d473b3ec6570950ce9ea`
(merge of develop `8bb344e32` into `auto-147`). All evidence below was executed by the
verifier, not inherited from the repair artifact.

## Issue acceptance — proven by execution

- `uv run pytest packages/maistro-core/tests/graph/nodes/test_agent_delegate_remote_child_run.py test_agent_delegate_remote_review.py test_agent_delegate_remote.py -q` -> 62 passed.
- Named acceptance nodes, all PASSED: in-process child Run (`TestDelegationFilesAChildRun::test_an_in_process_delegation_creates_a_child_of_the_delegating_node_run`), cross-instance child Run, both provenance nodes (task id + mode + both agents), both escape guards (`TestTheEscapeGuardsFire`, `RunIntegrityError` surfaced through `validate_child_scope` — the same guard `create_run` enforces, `runs/store.py:209/733`), resolver wiring (`TestTheResolverWiresTheNode`), loud refusals (`test_in_process_no_delegator_configured_is_a_refusal_not_a_result`, `test_cross_instance_no_guest_peers_configured_is_a_refusal_not_a_result`; `DelegationNotConfiguredError`, `output is None`).
- Full `packages/maistro-core/tests`: 10101 passed, 654 skipped, 1 xfailed. hive-conductor adapter suite: 9 passed.
- `uv run ruff check .` and `ruff format --check .`: clean. `mypy --strict packages/maistro-core/src`: clean after `uv sync --extra bootstrap` (the 5 import-not-found errors are env-only, in untouched `cli/_builders_tui.py`/`cli/_install.py`).
- Prior verification defect (receipt placeholder on the yielded Attempt) is repaired and pinned by `TestTheReceiptIsAttemptOwnedIdentity`: reservation Attempt carries `{"mode": ...}` only; the settling Attempt carries `task_id`; receipt still lands on Run provenance post-acceptance.
- Production reachability of the child-Run path: durable executor stamps `node_run_id`/`attempt_id` onto the ctx (`graph/durable_runs/attempt_executor.py` `context_for_attempt`); consumer path stamps it via `_with_attempt_identity` (wired at `runs/consumption.py:176/206`). `a2a_delegation` is absent from `CONSUMABLE_SOURCES`, so the child is never double-executed.

## Blocking finding: required ac-state gate is red at this head

`scripts/check-ac-state.py --run-tests --ratchet --mandate 8bb344e32` (exact CI command,
`.github/workflows/quality.yml:951-955`, required check) exits 1:

- With a migrated PostgreSQL (`MAISTRO_TEST_PG_DSN`, CI shape): every bound holds
  (design coverage measured 37.693% vs folded floor 36.5259%; contradicted 0;
  unverifiable 0; acceptance + chain mandates both OK) but the count ratchet refuses:
  `FAIL: unbanked improvement` — the branch must bank its improved bound and commit the
  folded note (`--bank`).
- Without PostgreSQL: the measured ratchet fails differently (`design_coverage 33.03
  below floors 33.91/36.53`) because DB-backed AC tests skip; environment-sensitive, not
  the merge blocker by itself.
- The branch's driver commit `1aa326b4b` rewrote `quality/ac-state-notes/_baseline.json`
  upward (design_coverage 21.3053 -> 36.5259) and deleted 68 note files, but never banked
  the head's own measurement, so the gate cannot pass at this head without one more
  bank+commit. The prior repair artifact's "check-ac-state ok" evidence covered only the
  unmeasured mode, which refuses cross-mode comparison (exit 0 without comparing).

## Non-blocking, checked

- `scripts/check-vulture-baseline.py` fails locally (exit 1) identically at base and head:
  raw `vulture packages/*/src --min-confidence 60` differs between `8bb344e32` and head by
  exactly 7 lines — the intended `register_agent_capability` ledger prune (the factory now
  calls it) plus line-number shifts. The large ledger mismatch is an environment artifact
  (vulture not in the project venv; ledger recorded under CI conditions), not a regression
  of this branch.
- PR body ("Refs #147") and branch commit messages contain no premature GitHub closure
  keywords.
