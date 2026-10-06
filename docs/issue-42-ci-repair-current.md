# Issue #42: current CI-repair checkpoint

## Revalidation at assigned HEAD 3fb0b2e2afe1 (job b7e5e805)

This section records the current round; the earlier checkpoint below is retained
as historical evidence, not assumed to be current verification.

- Frozen item: issue #42, branch/worktree `auto-42`; starting HEAD
  `3fb0b2e2afe1dca6713b15c1605bcc63715c751c`, supplied base
  `11376c7bef4ea7d17195b90bea8ca9a64a769bb1`. Worktree initially clean.
  Scope remains the named test/audit/vulture failures and acceptance validation;
  no GitHub mutations or unrelated repairs.
- Read repository instructions, accepted ADRs 1f7c, a66b, f383 and b36a, supplied
  dispatch evidence, check-0 through check-6, and the previous result artifact.
  b36a extends f383 with renewal/reclaim; Runtime remains mechanics-only and
  receives the persisted Attempt ID. No authority or architecture changes.
- `uv sync --locked --extra dev`: passed. Exact assigned
  `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: passed, 1,335 reviewed
  identities / 1,335 findings, zero unclassified. No ledger edit warranted.
- `npm --prefix packages/hive-conductor/frontend audit --audit-level=high` and
  the same command for `packages/maistro-canvas/frontend`: both passed, zero
  vulnerabilities. The historically reported source-map-js failure is not
  reproducible at this HEAD.
- Re-read `.github/workflows/security.yml`: **current CI uses `--all-extras`**,
  not merely dev. Ran `uv sync --locked --all-extras`, `uv pip install pip-audit`,
  `uv pip freeze --exclude-editable > /tmp/auto-42-round-deps.txt`, then
  `uv run pip-audit --strict --format=json -r /tmp/auto-42-round-deps.txt
  > /tmp/auto-42-round-audit.json` and `uv run python scripts/pip_audit_gate.py
  /tmp/auto-42-round-audit.json`. Raw audit exit 1: two report occurrences of the
  already-triaged ecdsa PYSEC-2026-1325. Policy gate passed, including dependency
  usage checks. No multidict/werkzeug finding, no allowlist changes.
- `DOCKER_HOST=unix:///var/run/docker.sock docker ps`: failed to connect to the
  daemon. Live PostgreSQL restart/concurrency validation remains blocked.
- `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest
  packages/maistro-core/tests/runs packages/maistro-core/tests/graph/durable_runs
  -x -q`: **1,762 passed, 295 skipped, 6 warnings** in 49 seconds. Log:
  `/tmp/auto-42-round-runtime.log`. Warnings are SQLite teardown threads;
  skipped PostgreSQL cases are not acceptance passes.

Fresh acceptance review confirms `runs/execution.py:395` persists a leased
Attempt before launch, and line 591 supplies that ID to Runtime. Its exception
path cancels and awaits live work before terminalization. The executed retry
correlation test reads IDs inside real executor work; the ambiguous-effect test
drives the durable Graph and Invocation service, asserting one dispatch across
three visits and original IDs on the UNKNOWN Invocation. The chat recovery suite
uses Container wiring and injected renewal/terminal-write failures, rather than
asserting only constructor settings. These are meaningful bounded checks, not a
proof of all physical paths or live cross-process durability. The supplied exact
issue entries show #1169, #1170 and #1194 closed; no remote re-enumeration was used.

Additional current-round results:

- `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest
  packages/maistro-core/tests/runtime
  packages/maistro-core/tests/integration/test_one_trace_end_to_end.py -x -q`:
  **29 passed**. The trace test emits real SQLite Events from inside an Attempt;
  it does not prove the Invocation leg or cross-process PostgreSQL correlation.
- With the same environment, `uv run pytest
  packages/hive-conductor/backend/tests/test_dag_run_cancel_route.py
  packages/hive-conductor/backend/tests/test_hyperlight_executor.py -x -q`:
  **13 passed**. The route test observes physical provider unwinding, and the
  subprocess failure test checks the child is reaped and its drain is settled.
- With the same environment, `uv run pytest
  packages/maistro-server/tests/test_task_restart_recovery.py -x -q -rs`:
  **1 skipped**, explicitly because `MAISTRO_TEST_PG_DSN` is unset.
- `uv run python scripts/check-execution-lifecycles.py`,
  `check-foreign-harness-egress.py` and `check-wiring-reads.py`: passed.
  They classify 19 lifecycles and retain 11 reviewed unread fields; these bounded
  checks are not exhaustive physical-call reachability proofs.
- Canvas frontend `npm ci`, `npm run test:ci`, `npm run lint`, `npm run build`,
  `npm audit --audit-level=high`: passed; **79 tests**, 13 existing lint warnings,
  bundle-size warning, zero audit findings.
- `uv run ruff check .`, `uv run ruff format --check .`, `git diff --check`:
  passed (3,003 Python files already formatted).

### Current acceptance disposition

| Criterion | Current-round evidence / remaining gap |
| --- | --- |
| Every physical execution has an Attempt | Persist-before-launch inspected; runs and durable Graph suites passed. Universal production-path coverage **UNVERIFIED**. |
| Chronological retries | Executed runs suite includes retry and correlation assertions for stable NodeRun and fresh Attempt IDs. Passed. |
| Canonical idempotency/effect replay contract | Executed ambiguous-effect test proves one dispatch across three Graph visits. Live PostgreSQL concurrency **UNVERIFIED**. |
| Physical cancellation/deadlines | Runtime, runs and shipped Hive cancellation/subprocess tests passed; arbitrary external provider abort behavior **UNVERIFIED**. |
| Chat lease/fence/reclaim and terminal-write repair | Executed chat recovery suite uses production Container wiring and injected failures. Live PostgreSQL crash/restart **UNVERIFIED**. |
| No migrated-core physical bypass | Bounded lifecycle, egress and wiring checks passed. Exhaustive absence **UNVERIFIED**. |
| Persistence/Event/Invocation correlation across retries/recovery | Executed correlation, trace, ambiguous-effect and available-backend spine tests passed; live cross-process PostgreSQL **UNVERIFIED**. |
| #1169/#1170/#1194 closed first | Exact supplied snapshot entries are closed (September 13, 10 and 29 respectively). |

**Current verdict: BLOCKED for full issue acceptance.** Fresh local runs total
1,804 Python passes, 296 skips and 79 frontend passes. The named audit/vulture
failures do not reproduce; no implementation, dependency or ledger mutation is
justified. Only this evidence document changes, so there is no test inventory
delta. The entire multi-package CI test job was not reproduced. Obtain its
current failing step log if it is still red, and provide a working PostgreSQL
service to finish live durability validation; complete the production bypass
review before declaring issue readiness. No issue closure or integration approval.

Checkpoint: `{checked: 1, done: 1, skipped: 0, errors: 1}`. The single assigned
repair item is revalidated; the environment error is the unavailable Docker
daemon. This checkpoint is committed locally; no push or GitHub mutation.

## Historical checkpoint (prior round)


## Frozen scope

- Only issue #42, branch `auto-42`, assigned worktree `/home/dev/Git/wt/auto-42`.
- Starting HEAD `6854b511807d87f561abb5e5509f4e6f3d3c3faf`; supplied develop base
  `7334621bf797178dd992622d55aaead33bf9d094`; both resolve locally.
- Initial worktree clean; no incoming changes require salvage.
- Evidence snapshot: job `7624b2a25cb645668801e8b6d97f6587` dispatch context,
  check-0 through check-6, and prior job `dc1ddd259a8243e282feafb04823f43e` result.
- Process only the assigned test/audit/vulture failures and issue #42 acceptance.
  No new issues, PRs, remote enumeration, or integration actions.
- Candidate repair files: frontend `package-lock.json`, `uv.lock` only if an
  actual audit failure requires dependency repair; `quality/vulture-baseline.json`
  only for reviewed scanner evidence under the explicit CI-repair exception;
  this validation record. Existing runtime implementations/tests and CI scripts
  are inspection/validation scope, not speculative rewrite targets.

## Initial evidence and assumptions

The driver logs show ruff and inventory gates passing and 607 tests passing,
124 skipped. SQLite teardown thread warnings occur. Prior repair reports audit
and vulture success but PostgreSQL and exhaustive bypass coverage unverified.
These claims will be independently checked, not taken as proof.

Ambiguity: the dispatch names a `test` failure but provides no current failing
step log. Assumption: reproduce the specifically reported npm audit, Python
supply-chain policy, and exact vulture command before changing anything. If
already green, retain existing fixes and record fresh evidence rather than
inventing a repair. Full issue readiness requires stronger evidence than a CI
repair handoff. This round must end with a local commit, no push.

## Fresh gate results

- `uv sync --locked --extra dev`: passed.
- Exact assigned `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: passed, 1,335 findings and
  1,335 reviewed identities, no unclassified findings. No ledger edit justified.
- `npm --prefix packages/hive-conductor/frontend audit --audit-level=high`:
  passed, zero vulnerabilities.
- `npm --prefix packages/maistro-canvas/frontend audit --audit-level=high`:
  passed, zero vulnerabilities. This is the frontend audited by CI `test`.
- `DOCKER_HOST=unix:///var/run/docker.sock docker ps`: failed, cannot connect to
  daemon. The claimed Docker availability is not true in this worktree's current
  environment. Do not report skipped PostgreSQL tests as passing.

The reported npm/vulture failures are not reproducible on the assigned HEAD;
retain existing dependency fixes and ledger rather than make cosmetic edits.

- `uv sync --locked --extra dev --extra bootstrap` then `REQUIRE_AUTH=false
  MAISTRO_DRY_RUN=1 uv run pytest packages/maistro-core/tests -x -q`: passed,
  **13,087 passed, 944 skipped, 1 xfailed, 56 warnings** in 243 seconds.
  Full output: `/tmp/auto-42-current-core.log`. Unlike the supplied focused
  selection, this executed the entire core package. Warnings include SQLite
  teardown threads and unawaited test-double coroutines; skips remain skips.
- Read accepted ADRs 1f7c, a66b, f383, b36a. Runtime execution identity must be
  the Attempt ID; retries preserve logical NodeRun identity. b36a's later
  lease-renewal/reclaim contract extends f383's originally narrower boundary.
  No architecture or authority changes are needed for this CI repair.
- `uv pip install pip-audit`; `uv pip freeze --exclude-editable`; `uv run
  pip-audit --strict --format=json -r /tmp/auto-42-current-deps.txt`; `uv run
  python scripts/pip_audit_gate.py /tmp/auto-42-current-audit.json`: policy gate
  passed. Raw audit exits 1 for existing ecdsa PYSEC-2026-1325, already triaged;
  no multidict/werkzeug findings and no allowlist changes. Audit environment is
  dev plus bootstrap, a superset of CI's dev sync.
- `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest
  packages/maistro-server/tests -x -q`: **515 passed, 9 skipped, 22 warnings**.
  Output: `/tmp/auto-42-current-server.log`.
- Same command for `packages/maistro-canvas/tests`: **464 passed, 75 skipped,
  53 warnings**. Output: `/tmp/auto-42-current-canvas.log`.
- These three complete package suites total **14,066 passed, 1,028 skipped,
  1 xfailed**. No production failure reproduced. In particular the server's
  live task restart test is skipped, not proven by this run.
- Canvas frontend: `npm ci`, `npm run test:ci`, `npm run lint`, `npm run build`,
  `npm audit --audit-level=high` all passed in `packages/maistro-canvas/frontend`.
  **79 tests passed**, 13 existing lint warnings, bundle-size advisory, zero
  vulnerabilities. Output: `/tmp/auto-42-current-frontend.log`.
- `uv run ruff check .` and `uv run ruff format --check .`: passed; 3,003 files
  formatted. `git diff --check`: passed.
- `uv run python scripts/check-execution-lifecycles.py`: passed (19 classified
  lifecycles); `check-foreign-harness-egress.py`: passed;
  `check-wiring-reads.py`: passed (11 reviewed unread fields, no new debt).
  These gates have bounded scopes and do not prove universal bypass absence.
- `uv run pytest packages/hive-conductor/backend/tests/test_dag_run_cancel_route.py
  packages/hive-conductor/backend/tests/test_hyperlight_executor.py -x -q`:
  **13 passed**, including shipped cancellation and subprocess cleanup paths.
- `uv run python scripts/check-suite-inventory.py --suite <suite>` passed for
  each of core (14,032), server (524), Canvas (519). Inventory collects in its
  controlled environment; these are collection counts, not executed outcomes.
  No tests changed, so no inventory delta or baseline amendment is needed.

## Acceptance evidence and limits

All test references below were exercised by the complete core/server/Canvas
package commands above, unless explicitly marked skipped. The separate Hive
command supplies physical cancellation/subprocess evidence. Tests were read to
confirm assertions exercise production seams, not just mocked status flags.

| Issue criterion | Reachable production behavior and executed evidence |
| --- | --- |
| Every physical execution has an Attempt | `runs/execution.py:395` persists the leased Attempt before `_launch_claimed`; line 591 passes its ID to Runtime. `runs/test_execution.py:75` asserts identity and terminal-persistence ordering. Chat and durable Graph suites also execute canonical adapters. Universal coverage of **every** production path remains **UNVERIFIED** in this bounded CI repair. |
| Retries create chronological Attempts | `runs/test_execution.py:319` exercises retry under the same NodeRun; `test_execution_is_correlated.py:76` reads IDs inside real executor work, asserting stable Run/NodeRun and a different Attempt. Passed. |
| Canonical replay/effect contract; no blind ambiguous-effect redispatch | `graph/durable_runs/test_ambiguous_effect_replay_guard.py:147` drives the real durable executor and Invocation service, asserts one dispatch across three visits, two refused retries, and original IDs on UNKNOWN Invocation evidence. Passed. Invocation-store/conformance suites passed on available backends; live PostgreSQL concurrency **UNVERIFIED**. |
| Runtime cancellation/deadlines stop work or classify truthfully | Runtime/run suites passed. `runs/execution.py:464` cancels and awaits live runtime work before recording terminal failure. Hive shipped cancellation and Hyperlight subprocess tests passed (13). This is bounded evidence, not certification of every external provider's abort behavior. |
| Chat leases/fencing/reclaim and terminal-write repair | `runs/chat_execution.py:213` defaults to an expiring lease and passes it into the canonical RunExecutionService. `runs/test_chat_attempt_recovery.py` exercises Container wiring, stopped renewals, fencing, retry and terminal-write failures; passed. Real PostgreSQL crash/restart **UNVERIFIED**. |
| No physical bypass on migrated core paths | Inspected Attempt launch, chat adapter, and durable Graph firewall; full core suite includes A2A/harness boundary tests. Lifecycle, foreign-harness egress and wiring gates passed. Exhaustive production physical-call reachability is **UNVERIFIED**; those gates are not equivalent to that proof. |
| Persistence/Events correlate across retries/recovery | `runs/test_execution_is_correlated.py`, `integration/test_one_trace_end_to_end.py`, spine conformance, and ambiguous-effect suites passed on available backends. Live server restart is skipped and cross-process PostgreSQL persistence/Event evidence remains **UNVERIFIED**. |
| #1169/#1170/#1194 close first | Read their exact entries from supplied dispatch snapshot: closed 2026-09-13, 2026-09-10, 2026-09-29 respectively. No new GitHub enumeration or mutation. |

ADRs remain authoritative: canonical Goal -> Graph -> Run -> NodeRun -> Attempt
execution and store ownership are unchanged. No competing scheduler, execution
identity, authorization path, store, or event authority was introduced.

## Disposition / handoff

**BLOCKED for full issue acceptance**, not a demonstrated production regression.
All specifically assigned npm audit, Python audit-policy, and exact vulture gates
pass on the starting HEAD. Full core/server/Canvas suites and focused Hive tests
provide **14,079 Python passes**, 1,028 skips, 1 xfail, plus 79 frontend passes.
The earlier dependency fixes are retained. No new dependency, implementation,
quality ledger, grant, inventory baseline, or test edits were justified.
Only this evidence/handoff document changes in this round.

The remaining blockers cannot be repaired by cosmetic code changes: Docker at
the instructed socket is unavailable, live PostgreSQL/restart/concurrency tests
were not run, and universal production bypass absence was not established. The
entire multi-package CI `test` job was not reproduced; its specifically reported
audit step and the relevant complete package suites were. Obtain the current
failing CI step log if `test` remains red after this head's already-landed fixes.

Progress: `{checked: 1, done: 1, skipped: 0, errors: 1}` — one assigned CI repair
item revalidated; one environment failure (Docker). Next: restore live database
validation and perform complete production-path acceptance review. Local commit
only; no push, PR, issue closure, or integration approval.
