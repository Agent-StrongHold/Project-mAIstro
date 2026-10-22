# Round 23 — independent verifier revalidation (head f31945d0e)

Read-only verifier round for issue #42 at `f31945d0e3beb86c61c6fb0d2fc145783477a948`
(develop base `680329c960cd722034bd0053be745f3de138ba8d`). No source changes; this
note is the only artifact.

## CI `test` gate failure — root cause and local proof

- Failing run `37233416409` was at head `889a8df4d` (the develop merge, *before*
  the fix commit). Failed step: `uv run pytest packages/maistro-core/tests` with
  `KeyError: 'replay_effect_key'` in
  `packages/maistro-core/tests/graph/nodes/test_foreign_harness_invocation.py`
  (`test_openclaw_and_pi_dispatch_through_governed_invocation`,
  `test_node_accepts_a_raw_session_provider_and_wraps_it`).
- `f31945d0e` renames the harness metadata to `effect_key` (and adds it to the
  paused-Graph state in `agent_spawn_harness.py`); the same tests pass at this head.

## Fix verification for the prior effect-scope finding

- `attempt_executor.py:707` binds `logical_effect_key` around `node.run(...)` via
  the new `bind_logical_effect_scope` ContextVar;
  `capabilities/invocation.py` resolves an omitted `effect_scope` from the binding
  before falling back to the per-NodeRun identity.
- Anti-regression proof (in-memory, no tree edits): with
  `bind_logical_effect_scope` no-op'd, `test_ambiguous_effect_replay_guard` fails
  with "the ambiguous external effect ran at most once"; at head it passes with
  `dispatches == 1`, `blocked_visits == 2`, three chronological NodeRuns
  (ordinals 1/2/3, one COMPLETED Attempt each) and a single UNKNOWN Invocation
  recorded under the stable run-scoped effect identity.

## Locally executed at this head

- Full CI-test-job pytest surface: bootstrap 237✓/1 skip, core 12201✓/792 skip/
  1 xfail, server 493✓/8 skip, canvas 464✓/75 skip, turing 210✓, turing/backend
  90✓, design 540✓/1 skip, root `tests/` 4340✓/90 skip, rsi+evolve 1955✓/6 skip.
- Pg invocation store: 11✓ with `DOCKER_HOST` Postgres.
- Focused lane set re-run: 577✓/124 skip (driver run: 588✓/124 skip incl. pg).
- Cancellation/deadline/chat-lease evidence: durable_runs + `test_human_verdict_deadline`
  + `test_container_chat_runs`: 647✓/39 skip.
- Gates (CI args): `check-execution-lifecycles.py` 19/19 classified;
  `check-reachability.py` (174 unreachable, all dispositioned);
  `check-reachability-dispositions.py` 49 groups; `check_direct_effects.py`
  59 sites dispositioned; `check-backlog-consistency.py` OK;
  `verify-monorepo-layout.sh` OK. Driver logs: ruff check/format clean;
  suite inventory matched (canvas 519, core 12994, server 501 node IDs).
- `uv run mypy` across package sources: clean (795 files).
- GitHub (read-only): PR #1326 head == `f31945d0e`; #1169/#1170/#1194 CLOSED;
  #42 OPEN; no closure keywords in PR body or base..HEAD commit messages.
- Develop-sync block from the previous round: already resolved by merge `889a8df4d`;
  `git diff --numstat <base>..HEAD -- quality/` is empty — no ledger rows lost.

## Residuals (honestly unverified)

- CI run `37234981284` for this head was still in progress at review time — no
  GitHub-green claim is made; the gate evidence above is local.
- hive-conductor frontend `npm ci/lint/build` and the OpenAPI types drift step were
  not run locally (empty `node_modules`); the backend dump itself succeeds
  (224 paths, 129 schemas). The reported CI failure was the core pytest step.
- `test_task_restart_recovery.py` skips without its local server environment.
