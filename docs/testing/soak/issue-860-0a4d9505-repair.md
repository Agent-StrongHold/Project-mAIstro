# Issue #860 — bounded repair, job 0a4d9505

## Frozen scope

- Only issue #860; branch `auto-860`, starting HEAD
  `1a98af5088125572a7bd6e8592ca188df388a0a3`, base
  `3c761d14db944a727fa0744444bc67cfe36d49f7`. Initial worktree clean.
- Inputs: supplied dispatch-context.json, prior result 0159386d, and prior
  check-3.log from job 98a11313. No check-*.log files present in this job directory
  at initial inspection. No GitHub mutations or refreshed issue lists.
- Repair candidates frozen to `packages/maistro-core/tests/persistence/test_pg_learnings.py`,
  its production `pg_learnings.py`, `quality/vulture-baseline.json` (only if actual
  scan requires reviewed amendments), this handoff and one inventory note if
  tests change. Read-only acceptance inspection: `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, load-profile/evidence docs, related ADRs,
  production rate-limit wiring and CI gate configuration.
- Ambiguity: dispatched prior failure may already be fixed at starting HEAD.
  Reproduce before editing. Exact promoted RC artifact/configuration is not supplied;
  do not substitute host preflight for promotion evidence.

## Initial evidence

Prior check-3.log reports 24 schema DDL statements versus 21 expected in the
schema-fence test. Prior result reports missing exact-RC soak and replica-local
rate allowances. These are leads, not current verification results.

## Validation and acceptance

Fresh validation: `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
passed (37 passed, 6 PostgreSQL-dependent skips, 1.60 s). The historical failure
is already repaired: the independent expected DDL list includes all three
Gauntlet validation columns. No test change is warranted.

Required exact vulture scan passed: 1323 reviewed identities / 1323 findings,
zero unclassified / never-allowlist. No ledger amendment is warranted.
Canonical Goal -> Graph -> Run -> NodeRun -> Attempt and existing security
authority remain unchanged.

Additional executed commands (1200-second tool timeouts):

| Command | Outcome |
| --- | --- |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3270 files |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q -rs` | 66 passed, 2.23 s |
| `uv run python scripts/check-ratchet-provenance.py` | PASS, 53 consumers; existing invalid-escape SyntaxWarnings |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |
| `git diff --check` | PASS |

Exact vulture arguments and companion gates were checked against
`.github/workflows/vulture-ratchet.yml:77-86`. The gate resolved its trusted
merge base to `4aa68edc0b6b`; it was not overridden with the dispatch base.
No full-tree pytest, live database test or new production soak was run. The
six skipped tests are not live PostgreSQL evidence. No tests or test counts
changed, so no inventory note is needed.

## Architectural reconciliation

Read Accepted ADR-081226-a66b (canonical lifecycle), ADR-081626-f383
(canonical-store leases and stale-writer fencing), ADR-082426-82c7
(occurrence claim belongs to the Run), and ADR-085 (canonical per-principal
rate limiting independent of token quota). Admission uniqueness cannot be
substituted for physical-work uniqueness. The lease ADR explicitly does not
yet define automatic expiry takeover of an apparently live Attempt; the issue
cannot authorize a competing reclaim implementation. No runtime or security
policy changes were made.

## Acceptance review — all ten criteria

| Criterion | Current evidence and disposition |
| --- | --- |
| Representative RC load profile | **UNVERIFIED**. Profile exists, but `scripts/soak/run_soak.py:1375-1397` uses one credential and health/task/receipt/metrics traffic. Concurrent Workspaces, Graph fan-out, successful tool/model execution, Canvas and worker coverage are not demonstrated. |
| At least two deployed application replicas | **UNVERIFIED** for the RC. Executed tests exercise ASGI limiter instances, not two deployed RC replicas. |
| Sustained saturation, queue growth, lease reclaim, retry/backoff, leaks and shutdown | **UNVERIFIED**. Real wrapper/child sampler test passed; no sustained production workload was run. |
| No duplicate physical schedule/task/Run/Attempt work; Goal reconciliation | **UNVERIFIED**. `scripts/soak/run_soak.py:1044-1069` explicitly cancels the schedule probe Run without execution. Admission evidence does not reconcile physical effects or Goals. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **UNMET as a shared allowance claim**. Freshly passing `tests/test_soak_promotion_gates.py:439` observes `[200, 200, 429]` independently on both real production limiter instances for the same IP/credential. Production registers this middleware at `packages/maistro-server/src/maistro_server/main.py:648`; `api/rate_limit.py:32-37` documents N-times aggregate allowance. Direct local 429 probes do not prove a shared budget. Full deployed security/degraded behavior remains **UNVERIFIED**. |
| Full telemetry and explicit thresholds | **UNVERIFIED**. Existing sampler regressions pass, but `scripts/soak/run_soak.py:1421` records driver-loop lag, not application-loop latency. No complete RC DB/worker/queue/error telemetry collected. |
| Active-work kill/restart proves drain/fencing/recovery | **UNVERIFIED**. Boot-cleanup regressions passed; `scripts/soak/run_soak.py:1439-1490` checks process exit/rejoin and request counters, not physical-effect reconciliation or stale Attempt ownership. |
| Long unchanged exact-RC soak | **UNVERIFIED / BLOCKED**. `scripts/soak/run_soak.py:730-741` always rejects host preflight as exact RC. Fresh four-hour synthetic CLI cases fail closed as intended. No exact image/configuration selected or soaked. |
| Findings filed/reclassified before promotion | Findings preserved locally here. External disposition **UNVERIFIED**; GitHub mutation prohibited. No closure or promotion requested. |
| Machine/human evidence bound to exact image/package/commit/config hashes | **UNVERIFIED** for RC. This report is focused validation only; no new RC machine evidence was generated. Historical evidence was preserved, not relabeled as current. |

## Final disposition

**BLOCKED for issue acceptance.** The supplied CI failure is stale, the explicit
vulture repair has no unbanked identities, and the previous acceptance block
remains. Neither a cosmetic runtime edit nor an unnecessary ledger amendment
would resolve it. A selected immutable RC/configuration, representative
production workloads, physical-work/recovery oracles, complete telemetry and a
new long unchanged-artifact soak are required. The replica-local rate-limit
acceptance mismatch also needs an explicit supported deployment resolution.

Only this handoff file changed. No new tests, production changes, ledger/grant
edits, GitHub mutations or destructive operations. Local commit required for
handoff. Progress: checked 1, done 0 (issue acceptance), skipped 0, errors 0
validation failures. Next: resolve the RC acceptance blockers, not redispatch
the already-passing schema/vulture checks as a repair.
