# Issue #42: current CI-repair checkpoint

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
