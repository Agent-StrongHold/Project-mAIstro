# Issue #860 repair checkpoint (b0e53c6f)

## Frozen scope

One item: issue #860, branch `auto-860`, starting HEAD
`9f9a411c356023fa71603c63b85da2fdee73749c`, develop base
`ac7370141e8e61bd6f352bca35ed0b505104aadb` (both resolved locally).
Initial worktree was clean. No incoming edits to salvage.

Inputs: supplied dispatch-context.json, prior result
7156f247a5c64fdc8cbc673455fa1dd6/result.json, prior failed
98a11313167b41a98a420abfda80c292/check-3.log. The current job directory
contains no check-*.log files at initial inspection.

Edit scope: this report and, only if actual scan evidence warrants it,
quality/vulture-baseline.json and the specific identities reported by the scan.
Read scope: existing #860 soak implementation, adjacent tests, policy/ADRs,
and supplied evidence. No GitHub mutations or new issue/PR enumeration.

Assumption: this is the writer CI-repair lane, not a read-only verifier lane.
A passing static gate is not proof of the ten load/soak acceptance criteria.

## Progress

- Exact requested vulture scan passed: 1322 findings / 1322 reviewed
  identities, zero unclassified and zero never-allowlist findings. No ledger
  amendment is justified; no debt was guessed.
- Supplied historical check-3.log is a schema test mismatch (24 statements
  versus 21), not vulture debt. Fresh command
  `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
  passed: 37 passed, 6 skipped. Live PostgreSQL tests were skipped.
- Prior result read: BLOCKED on missing exact-RC soak and cross-replica
  limitations. These claims still need fresh targeted verification.
- Attempted docs/testing/soak/README.md lookup: not found; skipped. The actual
  profile is docs/testing/soak/m3a-load-profile.md.
- No production or test edits warranted by checks so far.
- `uv run ruff check .`: passed. `uv run ruff format --check .`: passed,
  3301 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  73 passed. This executes real middleware and task-router ASGI probes,
  plus harness rejection/accounting tests; it does not deploy two replicas.
- `uv run python scripts/check-suite-inventory.py`: all 17 suites match;
  31323 unique identities and zero copied-test duplication. No tests added,
  so no inventory-delta note is required.
- Confirmed `.github/workflows/quality.yml:1079` uses the exact vulture
  invocation executed here.

## Architecture reconciliation

Read repository instructions, docs/README.md, accepted ADR-081226-a66b
(logical lifecycle), ADR-081626-f383 (Attempt lease fencing), and
ADR-082426-82c7 (schedule occurrence admission), plus proposed ADR-081
(deployment). Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`.
A unique admitted Run is not proof of unique physical execution. Lease expiry
alone is not reclaim authority; ADR-081626-f383 explicitly leaves takeover
outside its contract. Proposed deployment guidance is not an acceptance waiver.
No scheduler, store, event authority, authorization path or gate was changed.

## Fresh acceptance assessment

| #860 criterion | Evidence / remaining gap |
| --- | --- |
| Representative RC workload | UNVERIFIED. `docs/testing/soak/m3a-load-profile.md` defines preflight traffic but explicitly lacks concurrent users/Workspaces, fan-out, successful tool/model calls, Design/Canvas and Goal/background-worker workloads. |
| At least two deployed application replicas | UNVERIFIED. Two-instance ASGI probes passed; no exact-RC deployment executed. |
| Sustained saturation, queues, lease reclaim, retries, memory/fd/process leaks | UNVERIFIED. No long production run executed. |
| No duplicated physical work, including schedule/task/Run/Attempt admission and Goal reconciliation | UNVERIFIED. Harness admission tests do not prove physical execution or sustained reconciliation. |
| Replica-resistant rate/security/degraded enforcement | NOT PROVEN. Executed `tests/test_soak_promotion_gates.py:439` reproduces independent allowances: same identity gets 200,200,429 on each real limiter instance. Local enforcement is not a shared principal budget. |
| Required production telemetry with explicit thresholds | UNVERIFIED. Profile has thresholds but no fresh production time series. Driver loop lag and driver SELECT 1 are not application-loop or application query/pool telemetry. |
| Active-work kill/restart, drain, fencing and recovery | UNVERIFIED. No production restart; exit/rejoin and terminal counts do not prove physical-work recovery. |
| Long soak of exact RC artifact/config | UNVERIFIED. `scripts/soak/run_soak.py:744` explicitly rejects artifact equivalence; executed CLI tests reject synthetic four-hour preflight evidence. No selected immutable RC image/config supplied. |
| Findings classified at earliest broken milestone | UNVERIFIED for complete campaign. Existing limitations retained; no GitHub mutations performed. |
| Machine/human evidence tied to exact image/package/commit/config | UNVERIFIED at promotion grade. This report records local checks against starting source HEAD only. |

Additional fresh counterexample: executed
`tests/test_soak_promotion_gates.py:564` admits through the production task
router and observes a 200 locally then a 404 on a peer's process-local queue,
even with a shared canonical admission spine. This is not fixed by making
the load driver retry or pin requests to a replica.

## Handoff

BLOCKED on exact-RC production evidence, not a currently failing vulture gate
or the historical schema mismatch. Only this report changed. No justified
ledger amendment or runtime repair was identified in the bounded CI lane.
Next: the release owner must select the immutable RC image/configuration,
resolve or explicitly scope the exposed product-path limitations, and execute
a representative instrumented production soak of at least four hours with
physical-work and recovery observations. Repeating static checks or extending
the host preflight cannot satisfy that requirement.

Progress: {checked: 1, done: 0, skipped: 0, errors: 0,
next: exact-RC deployment selection and production soak}. This report is the
sole change in the local validation checkpoint commit; it grants no integration
or promotion approval.
