# #718 verifier follow-up (head 981f8d03d782fdde583c46f395cf4f52193abae9)

Independent re-execution of the lane battery on the exact head. Everything the
repair notes claim was reproduced, plus one acceptance gap they do not record.

## Re-executed, all green

- Lane battery (test_conductor, test_governed_quota, test_model_chat_egress,
  test_reconciled_usage_quota, test_sqlite_quota, test_reconciliation,
  test_log_redaction): `uv run pytest ... -q` -> 106 passed.
- hive adapter: `.venv/bin/python -m pytest
  packages/hive-conductor/backend/tests/test_maistro_core_adapter.py -q`
  -> 9 passed.
- Live migration chain + audit-scope migration against the lane Postgres
  (`MAISTRO_TEST_DATABASE_URL=...auto-718-pg-dsn`): 14 passed; single head
  (`036_audit_log_org_scope`, re-parented onto `041_quota_invocation_evidence`)
  confirmed by `alembic heads` and the head-pinning assertion.
- `ruff check .`, suite inventories (core 10831, hive 2668), canonical mypy
  (713 files), and the CI-argv quality gates with
  `RATCHET_BASE_REV=60862b6c...`: vulture `packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` exit 0 (ledger 1415 -> 1414), radon exit 0,
  reachability + dispositions exit 0.
- No premature closure keywords in the PR body ("Refs #718") or commit
  messages.

## Unrecorded acceptance gap: the TaskRunner conductor class

The cutover routes the chat door (`ConductorAgent` with `governed_egress`,
`maistro_server/main.py:_build_container`) and every hive Agent strategy
(`create_agents` -> `GovernedLLMClient`) through the canonical Invocation
recorder. A third production entry into the same conductor LLM path was left
unwired and is recorded nowhere on the quota ledger, with no unreported
marker:

- `packages/maistro-server/src/maistro_server/main.py:369` — the server's
  `/tasks` queue worker is built as `TaskRunner(queue, executor=conductor.run_task)`;
- `packages/maistro-core/src/maistro/tasks/runner.py:272` — the runner invokes
  `self._executor(request)` with no kwargs, so `governed_egress` stays `None`;
- `packages/maistro-core/src/maistro/agents/conductor.py` (`_call_gateway`) —
  with `governed_egress=None` the raw gateway POST runs and its usage is
  recorded by nothing (no Invocation, no `on_response`);
- `packages/hive-conductor/backend/services/engine.py:221` — hive demo mode's
  `LocalTaskBackend(executor=run_task, ...)` has the same shape.

Consequence against the issue's acceptance: a major production call class
(every admitted `/tasks` conductor completion, and hive-demo task execution)
is silently absent from the ledger, so per-provider rows present as complete
(no `usage_complete=False`, no `unreported_count`) while omitting it. This is
the same "ordinary production calls do not enter the ledger" defect #718
exists to close, surviving in one of `run_task`'s two server entry points.
The inventory note `issue-718-canonical-invocation-quota.md` records the
ConductorAgent and hive-strategy wiring but not this gap.

Repair shape (per the issue's stop condition): supply the canonical effect
authority to the TaskRunner executor the same way `ConductorAgent` does —
not a per-caller recording callback.

## Resolution (this change)

Both unwired entries named above now supply the canonical effect authority the
way `ConductorAgent` does — the authority, not a per-caller recording callback:

- `maistro_server/main.py` — `_build_container` returns
  `(container, governed_egress)` and the lifespan's `runner_executor` closure
  hands that egress (plus the deployment's Workspace) to `conductor.run_task`,
  so every admitted `/tasks` completion records Invocation/quota evidence.
- `hive-conductor` — `EmbeddedRuntime` carries a `governed_egress` built once
  over the Container's effect authorities and the same gateway endpoint the
  roster's model clients got; `MaistroCoreBridge` exposes it; demo mode's
  `LocalTaskBackend` executor is a governed closure over `run_task`. Production
  hive mode was already covered: `MaistroServerTaskBackend` submits through
  maistro-server's `/tasks`, which the server fix governs. A stub port (no
  bridge, no Container) keeps the raw call — that process has no canonical
  authority to cross and no ledger to write to.

Evidence: `test_taskrunner_quota_ledger.py` drives the real lifespan's executor
against a real Container and observes ledger movement plus the missing-usage
unreported marker; the hive adapter/engine tests pin the egress construction
and the demo executor's kwargs. Deltas recorded in
`718-taskrunner-conductor-ledger.md`.
