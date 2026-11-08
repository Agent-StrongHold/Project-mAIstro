# Issue #860 — fresh validation, job 80bdfba4

## Scope and disposition

Only issue #860 was processed in `/home/dev/Git/wt/auto-860`. Verified clean
starting HEAD `6f602fd8487b10354e9d90061667f6715f7f81c4` and supplied base
`3c761d14db944a727fa0744444bc67cfe36d49f7`. No incoming edits required salvage.
The frozen dispatch snapshot and prior result were inspected, without GitHub
refresh or mutation. No current-job `check-*.log` files were supplied.

**BLOCKED: production acceptance is not established.** The cited historical
`98a11313167b41a98a420abfda80c292/check-3.log` failure does not reproduce.
The exact requested vulture scan finds no debt requiring repair. No speculative
code changes, ledger amendments, or gate changes are justified by these results.
This report is the only repository change; no tests changed, so no inventory
delta note is required. This is not promotion or integration approval.

## Fresh validation

Logs are under `/home/dev/maistro/jobs/80bdfba426d54953b6be881422015ea4/`.
All commands below exited 0; scan timeout was 600 seconds and test/quality
batches used 1200-second timeouts.

| Command | Result | Log |
| --- | --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | 1323 reviewed identities / 1323 findings; zero unclassified or forbidden | `worker-vulture.log` |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q -rs` | 37 passed, 6 skipped (no migrated `MAISTRO_TEST_PG_DSN`) | `worker-schema.log` |
| `uv run pytest tests/test_soak_promotion_gates.py -x -q -rs` | 65 passed | `worker-soak-tests.log` |
| `uv run ruff check .` | PASS | `worker-ruff.log` |
| `uv run ruff format --check .` | PASS, 3270 files | `worker-format.log` |
| `uv run python scripts/check-deployment-claims.py` | PASS, existence check only | `worker-deployment.log` |
| `uv run python scripts/check-suite-inventory.py` | PASS, 17 suites / 31128 unique identities | `worker-inventory.log` |

Vulture arguments match `.github/workflows/vulture-ratchet.yml:82`. Its automatic
comparison base is `4aa68edc0b6b`, not the dispatch's supplied develop base.
No claim is made that the six skipped PostgreSQL tests or a deployed soak ran.

## Reachable behavior and architecture

Read repository instructions, documentation authority map, and accepted
ADR-081226-69ee, ADR-081626-f383, ADR-082526-b36a and ADR-085. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`. The later lease ADR requires
renewal/expiry reclamation rather than inferring death from restart. Admission
uniqueness is not evidence of unique physical execution. No alternative
scheduler, execution authority, event store, or authorization path was added.

- `packages/maistro-core/src/maistro/persistence/pg_learnings.py:215` acquires
  the transaction-scoped schema advisory lock before DDL. The independent
  ordered expectation in `packages/maistro-core/tests/persistence/test_pg_learnings.py:175`
  already includes the three validation-audit columns absent from the historical
  failing log. Fresh execution passes without changing this test.
- `packages/maistro-server/src/maistro_server/main.py:648` installs the production
  rate middleware. `api/rate_limit.py:93` creates its instance-local limiter.
  Executed `tests/test_soak_promotion_gates.py:439` observes `[200, 200, 429]`
  independently on each of two instances for the same identity, authenticated
  and unauthenticated. This falsifies a shared allowance at the production
  middleware seam, not via a fake limiter. It is not deployed traffic evidence.
  ADR-085's per-principal keying does not make allowances cluster-wide; #842's
  documented N-times aggregate scope does not waive #860's non-bypass criterion.
  Resolve that requirement through the existing enforcement owner, not a second
  authorization path in the soak driver.
- `scripts/soak/run_soak.py:730` explicitly rejects exact-RC certification for
  host-process topology; the driver's threshold path calls it at
  line 1552. A longer run of that harness cannot sign promotion.
- `deploy/docker-compose.prod.yml:11` describes a reference topology requiring
  production image pinning. No designated immutable promoted RC/configuration
  was provided in the assignment; building an arbitrary local image would not
  establish what #89 would promote.
- `docs/testing/soak/m3a-load-profile.md:151` records missing representative
  workloads and instrumentation. Its schedule probe admits and cancels a
  queued Run without executing it (lines 193–203); driver-loop measurements
  cannot certify application-loop latency. Historical artifacts were not
  recertified against this HEAD.

## Acceptance accounting

| Issue criterion | Evidence and disposition |
| --- | --- |
| Representative RC workload | UNVERIFIED: existing profile lacks concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and background-work applicability. |
| Two deployed application replicas | UNVERIFIED: two tested middleware instances are not deployed immutable RC replicas. |
| Sustained saturation, queue growth, reclaim, retry, leaks and shutdown | UNVERIFIED: unit regression runs are not sustained load observations. |
| No duplicate physical work across schedule/task/Run/Attempt/Goal operations | UNVERIFIED: no production physical-work witness executed. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | Independent allowances reproduced at production middleware seam; deployed non-bypass and broader security/degraded acceptance UNVERIFIED. |
| Complete telemetry with explicit thresholds | UNVERIFIED: no fresh RC PostgreSQL/application-loop/process/RSS/fd/queue/error time series. |
| Active-work replica kill/restart, drain/fencing/recovery | UNVERIFIED: no deployed active-work fault injection executed. |
| Long soak of exact promoted RC/configuration | BLOCKED / UNVERIFIED: designation absent; host preflight always fails artifact certification. |
| Findings filed/reclassified before promotion | Local disposition recorded here; external filing/reclassification UNVERIFIED, GitHub mutation prohibited. |
| Machine/human evidence tied to exact image/package/commit/config hashes | UNVERIFIED: these source-bound validation logs are not an RC evidence bundle. |

## Handoff

The prior deterministic failure is stale for this HEAD; do not repeat a guessed
schema or ledger repair against it. Required next input/work: immutable RC and
runtime configuration designation, representative production workloads and
physical-work/telemetry witnesses, and reconciliation of the replica-budget
claim. Then run the long exact-RC soak with active-work recovery probes and
publish hash-bound evidence. No short host-process run was substituted.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "RC designation and production-soak prerequisites"}`.
`git diff --check` passed before this report; final whitespace validation and
local commit are recorded in the job's worker notes. No GitHub mutations.
