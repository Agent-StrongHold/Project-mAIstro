# Issue #860 — bounded repair validation (job 2ab0a3b9)

## Frozen scope

- One item: issue #860, branch `auto-860`, starting clean at
  `3c09edb36006a6a42802b6f6743de91716c17a48`; base
  `2154f845347c9541016288c760f8da3f5cd2e064`.
- Inputs: supplied dispatch-context.json, prior result 59ddd9df, and reported
  failed check `/home/dev/maistro/jobs/98a11313167b41a98a420abfda80c292/check-3.log`.
- Inspection/validation surfaces: `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, `docs/testing/soak/m3a-load-profile.md`,
  server task admission/rate limiting and adjacent tests, relevant accepted ADRs,
  CI gate scripts/workflows, and `quality/vulture-baseline.json`.
- Write scope: this report; only evidence-supported repairs to those surfaces.
  No new scheduler, authority, policy, or promotion claim.
- Current job directory contains no `check-*.log` files. Driver checks therefore
  cannot be assumed to have run for this job.
- Assumption: this is the writer CI-repair round. A passing fresh scan does not
  justify changing the debt ledger merely because an earlier job failed.
- Dispatch records `complete_for_scope: true`; the previous missing-comment
  collection block must be checked against the supplied source, not re-fetched.

## Results

- Supplied dispatch contains all 928 issue comments; previous missing-source
  blocker resolved by inspection of the supplied snapshot (no API calls).
- Historical `check-3.log` fails a schema assertion: 24 DDL statements versus
  21 expected. It is not a vulture failure.
- `uv sync --locked --extra dev`: passed.
- Exact requested vulture scan: passed, 1323 findings / 1323 reviewed identities,
  zero unclassified and never-allowlist findings. Scanner base is `3c761d14db94`,
  not the supplied develop comparison base. No ledger amendment justified.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  37 passed, 6 skipped. Historical failure does not reproduce. Database-dependent
  skips are not live PostgreSQL evidence.

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3277 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  73 passed.
- `uv run python scripts/check-backlog-consistency.py`: passed, 168 items.
- `uv run python scripts/check-deployment-claims.py`: passed; static existence
  check only, not proof of a deployed topology.
- `uv run python scripts/check-execution-lifecycles.py`: passed, 19 classified /
  19 discovered lifecycles.

The requested vulture command was
`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`.
Commands ran with a 1000-second timeout. No full-tree pytest or live soak ran.

## Production reachability and ADR reconciliation

Read repository instructions, documentation authority map, accepted ADR-085,
ADR-081226-a66b, ADR-081626-f383, and proposed ADR-081. Preserve
Goal -> Graph -> Run -> NodeRun -> Attempt. The accepted fencing ADR explicitly
leaves expiry takeover/recovery supersession to a later reclaim contract; an
admission race cannot stand in for physical-work fencing. Proposed deployment
text does not waive issue acceptance or authorize a new scheduler.

- `packages/maistro-core/tests/persistence/test_pg_learnings.py:175–177`
  already expects the three Gauntlet audit columns missing from the historical
  failing test. Production `_EPISTEMIC_COLUMNS` includes them and
  `PgLearningStore.ensure_schema` takes the transaction-scoped advisory lock
  before the upgrade loop. Fresh tests cover the complete ordered DDL body;
  they do not prove live simultaneous PostgreSQL boots in this round.
- `packages/maistro-server/src/maistro_server/main.py:648` installs the real
  `RateLimitMiddleware`, whose constructor at `api/rate_limit.py:90–98` creates
  process-local state. The executed test at
  `tests/test_soak_promotion_gates.py:439` observes `[200, 200, 429]` on each
  instance for the same identity, both authenticated and unauthenticated.
  Changing replica obtains independent allowance; this is negative evidence
  for the non-bypass requirement, not a deployed security certification.
- `packages/maistro-server/src/maistro_server/api/tasks.py:117` maps canonical
  Run ceiling rejection to 429. The executed task-route regression exercises
  real admission wiring, principal isolation and successful retry after a
  slot frees, but intentionally starts no worker.
- `scripts/soak/run_soak.py:744–755` rejects its own host-process topology as
  exact RC evidence. The executed CLI regression at
  `tests/test_soak_promotion_gates.py:103` rejects even otherwise-passing
  synthetic four-hour evidence without the RC artifact check.
- `scripts/soak/run_soak.py:1067–1092` cancels the schedule admission probe Run
  without execution. It cannot prove physical Attempt uniqueness/recovery.

## Acceptance matrix

| Criterion from captured issue #860 | Evidence and disposition |
|---|---|
| Representative RC users/Workspaces, request mix, fan-out, schedules, queue, tools/models, Design/Canvas and background workers | UNVERIFIED. `m3a-load-profile.md` explicitly records missing representative surfaces; no selected immutable RC configuration was supplied to justify exclusions. |
| At least two deployed application replicas | UNVERIFIED. ASGI middleware instances are not deployed RC replicas. |
| Sustained saturation, queues, expiry/reclaim, retry/backoff, growth/leaks and restart | UNVERIFIED. No sustained production window executed. |
| Schedule/task/Run/Attempt/Goal uniqueness without duplicate physical work | UNVERIFIED. Admission tests and cancelled probe Runs do not execute physical work or Goal reconciliation. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | Independent allowances reproduced by the production middleware test above; deployed concurrency/security/degraded behavior UNVERIFIED. |
| PostgreSQL, application loop, worker/process, RSS, descriptors, queue and error telemetry with thresholds | UNVERIFIED. Existing profile acknowledges instrumentation limits; driver loop lag is not application loop latency. No fresh deployment series captured. |
| Kill/restart during active work with drain/fencing/recovery | UNVERIFIED. No active physical Attempt restart experiment executed. |
| Long soak of exact RC artifact/configuration | UNVERIFIED. Current preflight fails exact-artifact certification by design. No immutable RC image/configuration supplied or exercised. |
| Findings filed/reclassified before promotion | Partial: `BACKLOG.md:267–279` records engine-116 as a specification gap and backlog validation passes. Completeness against a real RC soak is UNVERIFIED; no GitHub mutation. |
| Machine/human evidence tied to exact image/package/commit/config hashes | UNVERIFIED. This local validation report is not an RC evidence pack. |

## Disposition

BLOCKED for issue acceptance. Historical check failure is already repaired in
this tree, and the mandated scan reports no unbanked identities. No speculative
code or ledger changes were made. Only this report changes; no tests added or
removed, inventory delta zero (no inventory note needed). Inherited work is
preserved. No merge conflicts or evidence of a develop-sync conflict existed.

Next required input/action: designate the immutable RC image and configuration,
resolve the cluster-budget specification, complete representative workload and
application telemetry, then execute the profile's at-least-four-hour exact-RC
soak with active-work restart/fencing/recovery evidence. Re-dispatching the stale
schema failure is not a substitute for these prerequisites.

Progress: checked 1, done 1 local validation/handoff, skipped 0 issues, errors 0
validation commands. Local commit is a handoff only, not integration approval.
