# Issue #860 — repair checkpoint (job 4f6290d7)

## Frozen scope

- Only issue #860, branch `auto-860`, starting head
  `32e05cbe45db58309ce92ba9cedd0837fc017da4`, base
  `321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`.
- Worktree clean on arrival; no incoming edits to salvage.
- Repair candidates: `packages/maistro-core/tests/persistence/test_pg_learnings.py`,
  its production `pg_learnings.py`, `quality/vulture-baseline.json` only if the
  mandated scan identifies reviewed retained debt, and an inventory note if tests
  change. This report is the checkpoint/output file.
- Read-only acceptance surfaces: `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, existing load-profile/evidence documents,
  related server task/rate-limit implementations and their adjacent tests.
- No PR processing, GitHub mutations, or develop merge: no conflict on arrival.

## Initial evidence

The assigned job directory contains no `check-*.log` files in its initial
snapshot. The supplied prior `98a113.../check-3.log` reports the schema-fence test
expected 21 statements but observed 24. This is historical evidence, not a fresh
failure. The supplied prior result is BLOCKED on exact-RC soak and replica-local
enforcement/receipt visibility; those claims require independent validation.

Assumption: the explicit writer/CI-repair assignment applies, not the generic
verifier-only prohibition. No ledger change will be made without scan evidence.

## Fresh CI reproduction

- Mandated vulture command passed: 1322 reviewed identities / 1322 findings,
  zero unclassified and zero never-allowlist findings. No ledger amendment is
  warranted; adding entries would be a guessed repair.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
  passed: **37 passed, 6 skipped**. The historical schema-fence failure is already
  repaired: lines 174–179 independently enumerate all three validation-audit
  columns. No test weakening or production change is needed for that log.
- An initial local JSON inspection command failed because `issue` is an integer,
  not an object; corrected inspection read the captured issue source body.

The historical failed check is explicitly resolved on this starting tree, not a
current repair target.

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3301 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py -x -q`: **72 passed**.
  This executes the production middleware independent-allowance regression (both
  identities obtain `[200, 200, 429]` separately on each replica), the production
  task router receipt regression (owner 200 / peer 404), and the CLI rejection
  tests for four-hour evidence without an exact RC artifact. ASGI replicas and
  synthetic evidence are explicitly not deployed production soak evidence.
- A search used a nonexistent `middleware/rate_limit.py` path; not found, skipped.
  The test imports identify the real implementation as `api/rate_limit.py`.

## Architecture reconciliation

Read repository instructions, the documentation authority hierarchy, ADR-081,
ADR-081626-f383 and ADR-082826-b601. ADR-081 is **Proposed**, not an accepted
multi-replica guarantee. The accepted lease ADR reserves execution authority to
canonical Attempt leases and explicitly does not itself define expiry takeover.
The accepted consumer ADR requires canonical lifecycle transitions and the one
Run/NodeRun/Attempt execution spine, not a substitute soak scheduler. No authority,
authorization, or reclaim semantics are changed in this round.

## Remaining validation

- `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  **1 passed** (production route maps concurrency exhaustion to retryable 429).
- `uv run python scripts/check-suite-inventory.py`: passed, 17 suites match,
  31,323 unique identities, no duplicate evidence. No tests were added or changed,
  so no inventory delta is necessary.
- `uv run python scripts/check-backlog-consistency.py`: passed, 168 items.
- `git diff --check`: passed before final report completion; repeated at commit.

## Acceptance audit (all ten issue criteria)

| Criterion | Fresh evidence / disposition |
| --- | --- |
| Representative RC profile | **UNVERIFIED**. `m3a-load-profile.md` explicitly lists absent multi-user/Workspace traffic, Graph fan-out, successful tool/model calls, Design/Canvas and Goal/background workloads. A documented preflight mix is not the complete representative RC profile. |
| At least two deployed replicas | **UNVERIFIED** for the exact RC. Fresh tests instantiate two ASGI apps, not deployed replicas; historical shakedown claims are not independently repeated in this round. |
| Sustained saturation, queues, reclaim, retries, leaks and restart | **UNVERIFIED**. No sustained production run executed. Passing sampler regression tests do not establish long-window behavior. |
| No duplicate physical work | **UNVERIFIED**. Task-admission probe tests validate observed canonical identity accounting, not physical Attempt effects. The profile's schedule probe admits then cancels a Run; it does not prove execution/reclaim/reconciliation uniqueness. |
| Replica-selection-resistant limiting/security/degraded behavior | **NOT PROVEN**. `tests/test_soak_promotion_gates.py:439` freshly reproduces independent allowances using production middleware. `api/rate_limit.py:31` documents N-times-limit process-local semantics, with per-instance construction at line 94. This is an explicit mismatch with the stronger issue requirement, not permission to add a second authorization path. |
| Complete telemetry and thresholds | **UNVERIFIED**. Profile describes driver event-loop lag, not application event-loop lag, and reports missing worker/pool/reclaim observations. Passing sampler tests establish local measurement structure only. |
| Active-work kill/restart with drain/fencing/recovery | **UNVERIFIED**. CLI gate tests are not a kill during real physical work. The owner/peer receipt test (`tests/test_soak_promotion_gates.py:569`) freshly observes 200/404 via `api/tasks.py:144`, so receipt locality remains relevant to recovery evidence. |
| Long exact-RC artifact/configuration soak | **UNVERIFIED / BLOCKED**. `scripts/soak/run_soak.py:744` deliberately reports host preflight `ok=False`; CLI tests confirm even four-hour evidence fails without exact artifact identity. No exact RC image/config selection or promotion-grade run is produced here. |
| Findings classified to earliest invariant | **UNVERIFIED** for completeness. Existing evidence pack records M3-A/durable-state findings, but fresh production load discovery and exhaustive classification were not executed. No GitHub filing/mutation is permitted in this lane. |
| Machine/human evidence bound to exact artifact hashes | **UNVERIFIED** for promotion. This report binds fresh local validation to the starting head; it is not image/config-bound soak evidence. Historical packs must not be promoted as current observations. |

## Disposition and handoff

**BLOCKED**, not merge-ready. The named CI failure and vulture repair request
have no remaining failing evidence on the assigned starting tree. No source,
test, ledger, grant, threshold or historical evidence edits were warranted.
Only this report changed; it records fresh results rather than fabricating a
repair or repeating an inadequate preflight run.

Next required work: select and hash the exact deployable RC configuration,
complete its representative production workloads and application telemetry,
resolve the per-replica allowance contract and receipt/recovery gaps through
canonical owners, then execute the >=4-hour soak with active-work failure and
physical-effect accounting. Any runtime/config change requires a new run.
The shorter host-process harness cannot satisfy that handoff by duration alone.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "exact-RC production soak and unresolved acceptance gaps"}`.
The single assigned issue was checked; acceptance remains incomplete. Local
inspection mistakes above are recorded separately from validation failures.

