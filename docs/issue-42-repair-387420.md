# Issue 42 repair — job 387420793df94683812cb2ceefa0deb5

## Scope and salvage

Only issue #42 and its supplied test/audit/vulture failures were processed, in
`/home/dev/Git/wt/auto-42`, branch `auto-42`. Starting HEAD was verified as
`17fa7f7625a10a6f9e04ff2b1c5d01f2de58b272`. Read repository instructions,
the supplied dispatch snapshot/previous result, all seven driver check logs,
and accepted ADRs 1f7c, a66b, f383 and b36a. No GitHub mutations.

The starting tree was **not clean**: an unfinished merge of
`ce19fd99e40503185a3a3890a7bdf259d7c998ab` had a conflict in
`packages/maistro-core/src/maistro/a2a/guest_peers.py`. Saved unstaged and staged
patches to `../incoming-42.patch` and `../incoming-42-index.patch` before editing.
Driver Ruff and pytest/inventory collection failures stemmed from that syntax
error; their earlier outcomes were not treated as acceptance evidence.

Fetched origin once as requested. `origin/develop` resolved to the exact supplied
base `a8258ee24dd957d0f0b302db4eee90661fe23439`; the unfinished merge head was its
ancestor. Completed that merge first, then merged this develop ref, preserving
incoming work. The second merge's patches are saved at
`../incoming-42-develop.patch` and `../incoming-42-develop-index.patch`.

## Evidence-based repairs and changed files

Local merge commits:

- `35134ab2b`: resolve transport conflict and semantic integration failures.
- `1600faac5`: finish develop sync and inventory conflict reconciliation.

Focused repair files (apart from unchanged incoming develop changes):

- `packages/maistro-core/src/maistro/a2a/guest_peers.py`: retain incoming
  canonical caller/Goal/scope admission, transport provenance, and key agreement;
  retain existing authenticated reconciliation and the nonempty dispatch-receipt
  cache guard. Remove conflict markers/duplicated dispatch completion code.
- `packages/maistro-core/src/maistro/graph/nodes/agent_delegate_remote.py`:
  real conformance failed after syntax repair: incoming code passed removed
  `logical_effect=True` to the canonical Invocation service. Use the stable
  delegation key as `effect_scope` consistently for dispatch, completed lookup,
  and recovery. This is the existing canonical effect contract, not a new one.
- `packages/maistro-core/tests/a2a/test_guest_peers.py`: add empty-receipt
  recovery regression. One POST with an empty response must not prevent a GET
  recovering the receipt; that actual receipt is subsequently cached.
- `packages/maistro-core/tests/graph/nodes/test_agent_delegate_remote.py` and
  `test_agent_delegate_remote_governance.py`: two incoming tests expected replay
  metadata no longer authored by BaseNode. Compare against the canonical
  replay-key function instead; do not change metadata ownership to fit fixtures.
  Parameterize crashed RUNNING dispatch recovery across same/new NodeRun,
  asserting one original Invocation and preserved original Attempt correlation.
- `docs/testing/inventory-notes/auto-42-387420-merge-repair.md`: +2 cases.
- `docs/testing/inventory/baseline.json`: second merge conflicted between old
  develop counts and branch-compacted counts. Preserve compacted counts/folded
  notes and add develop's SDK suite at zero; its incoming notes supply its count.
  Executed inventory checks prove consistency; no arbitrary count changes.
- This report. Incoming #956/#959, extension SDK and pack-lifecycle source,
  tests, notes, scripts/workflows and lockfile changes remain preserved as develop
  merge content, not newly authored issue-42 feature work.

No quality ledger/grant changed in this round. The exact vulture scan reports
1,332 reviewed identities and zero unclassified, so inventing ledger edits is
not justified. `git diff 17fa7f762 HEAD --numstat -- quality/` was empty after
both merges. No dependency lockfile/audit-policy repair was justified by the
fresh audit results.

ADR reconciliation: Runtime is mechanics only, with execution ID = Attempt ID;
Run persistence owns leases/fences. b36a extends f383's earlier boundary with
liveness-based renewal/reclaim. The merge keeps canonical effect-scope admission
rather than reviving a caller-selectable parallel identity contract.

## Executed validation

Logs are under `/home/dev/maistro/jobs/387420793df94683812cb2ceefa0deb5/`.
All commands used long timeouts and the assigned worktree.

- `uv sync --locked --extra dev`: passed before and after sync.
- `uv run ruff check .`; `uv run ruff format --check .`: passed after both
  merges (3,035 Python files).
- Initial A2A/delegation/extensions run: 112 passed then a real TypeError
  exposed the removed Invocation keyword. Next run: 276 passed then stale
  BaseNode metadata expectation failed. Repairs above address both failures.
  Final focused run: **635 passed** (`worker-merge-tests.log`).
- New regression fault injection, using a temporary pytest plugin outside the
  tree, not editing tracked source:
  - caching the empty receipt makes `test_empty_dispatch_receipt...` fail
    (`worker-mutation-empty.log`);
  - stripping effect scopes from Invocation dispatch/lookup makes fresh-NodeRun
    recovery leave the old row RUNNING and create a second row, failing the
    original-row completion assertion (`worker-mutation-scope.log`).
  - without injection, all **3** new/parameterized cases pass.
- Local PostgreSQL 18 is online. Created isolated database `auto42_387420`,
  owned by the previous round's dedicated test role. Credentials remain only in
  mode-0600 `/tmp/auto-42-387420-pg.env`, never in git/log output.
  `uv run alembic upgrade head`: passed through `058` (`worker-migration.log`).
- With `MAISTRO_TEST_PG_DSN` set, `DATABASE_URL` and
  `MAISTRO_TEST_DATABASE_URL` unset, `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1`:
  `uv run pytest` over core `tests/runs`, `tests/runtime`,
  `tests/graph/durable_runs`, `tests/a2a`, `tests/extensions`, the four
  `test_agent_delegate_remote{,_child_run,_governance,_review}.py` suites,
  capability binding/durable approval/Invocation/PG Invocation/PG approval
  suites, and `tests/integration/test_one_trace_end_to_end.py`, with `-x -q`:
  **2,819 passed, 3 skipped, 5 warnings** (`worker-core-runtime.log`).
  Warnings are SQLite worker threads observing closed event loops; not silently
  counted as a clean warning-free run. Run-store PostgreSQL legs executed;
  `test_pg_invocation_store.py` explicitly uses a fake pool.
- With both database variables configured, server
  `tests/test_task_restart_recovery.py -x -q -rs`: **1 passed**, not skipped
  (`worker-restart.log`): real HTTP admission, SIGKILL, restarted lifespan and
  independent durable projection. Server `tests/api/test_a2a_api.py -x -q`:
  **3 passed** (database URL unset for ordinary fixture defaults).
- Hive backend `test_dag_run_cancel_route.py` and `test_hyperlight_executor.py
  -x -q`: **13 passed**, including physical unwind/process cleanup
  (`worker-cancellation.log`).
- With `MAISTRO_TEST_DATABASE_URL` pointing only at the isolated database,
  `uv run pytest tests/migrations/test_capability_invocation_effect_index_migration.py
  tests/migrations/test_migration_chain.py
  packages/maistro-core/tests/capabilities/test_issue55_hardening.py -x -q -rs`:
  **18 passed** (`worker-pg-schema.log`). These check live schema/round trips,
  not concurrent production Invocation dispatch. Fixtures downgrade their
  isolated database; migrate it again before reuse.
- Nonduplicated final test commands above: **2,854 passed, 3 skipped**. The
  635-case precursor run and mutation reruns are not added again.
- `uv run python scripts/check-suite-inventory.py --suite <suite>`: passed for
  core **14,336**, server **525**, canvas **519**, design **573**, SDK **118**
  (`worker-inventory.log`). All driver collection failures resolved.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: passed after final sync,
  **1,332 reviewed identities**, zero unclassified (`worker-vulture-final.log`).
- `check-execution-lifecycles.py`, `check-foreign-harness-egress.py`, and
  `check-wiring-reads.py`, each via `uv run python`: passed. Lifecycle gate
  reports 19 classified vocabularies; wiring gate matches 11 reviewed unread
  fields. Bounded gates are not universal reachability proofs.
- Hive and Canvas frontend `npm audit --audit-level=high`: both passed, zero
  vulnerabilities. The supplied source-map-js finding does not reproduce.
- CI supply-chain commands: `uv sync --locked --all-extras`, `uv pip install
  pip-audit`, `uv pip freeze --exclude-editable`, `uv run pip-audit --strict
  --format=json -r <worker-deps.txt>`: raw audit exit 1 for two occurrences of
  the existing ecdsa PYSEC-2026-1325 only. `uv run python
  scripts/pip_audit_gate.py <worker-pip-audit.json>` passed, including direct
  dependency usage. No multidict/werkzeug findings; no allowlist changes.

## Acceptance check — not integration approval

| Issue criterion | Fresh evidence and remaining limit |
| --- | --- |
| Every physical execution has an Attempt | `runs/execution.py:395` creates the leased Attempt before launch; `:594` passes its ID to Runtime. Inspected task/chat/Graph adapters route through this seam and execution suites passed. Universal scope **UNVERIFIED**: `tasks/runner.py:286` retains a compatibility fallback without an Attempt. Server wiring supplies `TaskAttemptExecutor` at `maistro_server/main.py:511`. Hive `services/engine.py:439-469` restricts its local backend to demo mode and passes its configured admitter/store; this is not evidence that every possible library composition is fenced. |
| Retries create chronological Attempts | Passing execution/fencing/correlation suites and live three-backend spine conformance verify fresh Attempt IDs/ordinals/fences without rewriting the previous physical history. |
| One replay/effect contract, no blind ambiguous redispatch | Passing real durable-Graph ambiguous-effect guard, live Run-store effect-claim conformance, and repaired delegated Invocation crash recovery; the new mutation proves the original Invocation must settle across new NodeRuns. Concurrent **production PostgreSQL Invocation** dispatch remains **UNVERIFIED**: its direct suite uses a fake pool; live migration coverage is not a concurrency test. |
| Cancellation/deadline crosses Runtime and work stops or is classified | `runs/execution.py:466-470` cancels and awaits physical work on failure. Runtime/core suites plus 13 Hive cancellation/Hyperlight tests pass and observe cleanup, not just status. No universal third-party provider abortability certification claimed. |
| Chat leases/fences/reclaim and terminal-write recovery | `runs/chat_execution.py:212-224` wires TTL into the canonical service; chat recovery suite passes injected renewal/terminal-write failures and retry/fence checks; PostgreSQL shared lease conformance passed. Real PostgreSQL **chat** process-death/terminal-write recovery remains **UNVERIFIED**: the actual SIGKILL test is tasks, while chat's Container fixture is in-memory. |
| No direct physical bypass on migrated core paths | Production server task wiring, Container chat adapter, durable Graph Attempt executor and runtime-constructor call sites inspected; bounded lifecycle/egress/wiring gates pass. Exhaustive reachability proof around optional compatibility compositions remains **UNVERIFIED**, not a demonstrated newly introduced server bypass. |
| Persistence and Events/Invocations stay correlated across retry/recovery | Passing execution-correlation/one-trace suites, new delegation recovery assertion preserving original NodeRun/Attempt, live PostgreSQL spine and HTTP task restart. Combined PostgreSQL Event+Invocation crash/retry E2E remains **UNVERIFIED**; do not equate separate tests with that trace. |
| #1169/#1170/#1194 closed first | Supplied exact dispatch snapshot records them closed on 2026-09-13, 2026-09-10 and 2026-09-29 respectively. No remote re-enumeration or issue mutations. |

## Handoff

**NEEDS-DEEP-REVIEW for complete issue acceptance.** The supplied merge/collection
block and actual semantic integration failures are repaired and locally committed.
Named audit/vulture failures do not reproduce. The whole multi-package CI test job
was not reproduced; retain the explicit acceptance gaps above rather than
manufacturing source/ledger changes or claiming integration approval.

Next bounded acceptance work: real PostgreSQL Invocation concurrency and combined
Event correlation under retry, plus PostgreSQL chat process-death/terminal-write
recovery. These require meaningful production-path tests, not another rerun of
the fake-pool or in-memory suites. No further issues were started.

Progress: `{checked: 1, done: 1, skipped: 0, errors: 0, next: bounded acceptance
review above}` for the assigned repair item. Historical failing commands and
mutation failures are documented above; no unresolved validation failure was
hidden. Work is committed locally; no push, PR, merge-to-protected-branch,
integration approval, or issue closure.
