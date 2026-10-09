# Issue #860 repair — 99e544f1

## Frozen scope

- Only issue #860, branch `auto-860`, starting HEAD
  `5d0480c76bcd558785b0e93026db1b0b16933355`, supplied develop base
  `c4bd944393ad7944ac1593013a817b5b22e04dc8`.
- Initial worktree was clean. No merge conflict or incoming changes to salvage.
- Inputs: supplied dispatch-context.json, prior result a04ced3b, and prior
  failed check `/home/dev/maistro/jobs/98a11313167b41a98a420abfda80c292/check-3.log`.
  No check-*.log files were present in this job directory at startup.
- Candidate repair files: `packages/maistro-core/tests/persistence/test_pg_learnings.py`,
  `packages/maistro-core/src/maistro/persistence/pg_learnings.py`,
  `quality/vulture-baseline.json` (only if the prescribed scan identifies debt),
  this report, and `docs/testing/inventory-notes/m3a-860-99e544f1.md` if tests change.
- Read-only acceptance inspection: `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, production rate middleware and deployment,
  relevant ADRs, `docs/testing/soak/m3a-load-profile.md`, historical evidence
  `docs/testing/soak/evidence/m3a-round30-shakedown.json`, adjacent tests and CI gates.

## Initial evidence and assumption

The supplied failed check asserts 21 schema statements but observed 24. This
may already have been repaired in the supplied HEAD; reproduce before editing.
The prior result reports missing deployed exact-RC soak evidence; unit tests
cannot replace it. No deployment artifact/configuration was supplied for a new
promotion soak. Do not infer promotion readiness from historical shakedowns.

## Validation and disposition

- `uv sync --locked --extra dev`: PASS.
- Prescribed exact Vulture scan: PASS, 1326 findings / 1326 reviewed identities,
  zero unclassified or never_allowlist; checker selected base `e46ad6708fda`.
  There is no scanner evidence justifying a ledger change.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  37 passed, 6 skipped. The supplied failure no longer reproduces: the existing
  expected DDL already includes all three Gauntlet audit columns. Skipped tests
  are not live database proof.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  74 passed. No test/source edit is supported by these results.

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3195 files.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `uv run python scripts/check-ratchet-provenance.py`: PASS, 52 quality JSON
  consumers. Non-failing syntax and local CORS warnings were emitted.
- `git diff --check`: PASS.
- `uv run python` importing the current soak runner and evaluating
  `docs/testing/soak/evidence/m3a-round30-shakedown.json`: asserted exactly
  `sustain_duration` and `exact_rc_artifact` fail. Observed duration is 420.08 s,
  minimum 14400 s; current `preflight_artifact_check()` also returns false.
  This is reevaluation of historical evidence, not a newly executed soak.

## Architecture and acceptance evidence

Read accepted ADR-087 (additive schema evolution), ADR-081626-f383 (Attempt
lease/fencing), ADR-082426-82c7 (occurrence claim), ADR-085 (principal limits),
and ADR-083026-a91e (unmeasured metrics). No runtime authority is changed:
`Goal -> Graph -> Run -> NodeRun -> Attempt` remains canonical.

ADR reconciliation: occurrence admission uniqueness is not unique physical
execution; Attempt fencing does not by itself define expiry takeover. Driver
loop latency is not application loop latency. An absent measurement cannot be
reported as a passing zero. The middleware's documented process-local scope
does not satisfy #860's stronger replica-selection acceptance requirement.

Production `packages/maistro-core/src/maistro/persistence/pg_learnings.py:216`
places the advisory lock before DDL inside one transaction. The passing schema
regression independently enumerates the DDL, including the three audit columns
at `packages/maistro-core/tests/persistence/test_pg_learnings.py:172` missing
from the historical failed log. No weakening of that assertion is needed.

Production `packages/maistro-server/src/maistro_server/main.py:648` installs
`RateLimitMiddleware`; `api/rate_limit.py:93` constructs an instance-local
`InMemoryRateLimiter`. The executed test at
`tests/test_soak_promotion_gates.py:439` uses this middleware and confirms
`[200, 200, 429]` independently from both replicas for the same credential/client.
It falsifies shared-allowance behavior, but is not a live deployment soak.

| Acceptance criterion | Evidence / disposition |
| --- | --- |
| Representative RC workload | **UNVERIFIED.** `docs/testing/soak/m3a-load-profile.md:152` explicitly lacks multi-user/Workspace, Graph fan-out, successful tools/models, Design/Canvas and Goal/background work. RC-specific inclusion/exclusion is not established. |
| At least two deployed application replicas | **UNVERIFIED for RC.** `deploy/docker-compose.prod.yml` declares two servers and shared services; current runner is a host-process preflight. No new deployment executed. |
| Sustained saturation, queue growth, expiry/reclaim, retries, resource leaks and restart | **UNVERIFIED.** Historical evaluator rejects 420.08 seconds versus 14400; passing sampler/accounting tests are not long-running service observations. |
| No duplicate physical work across schedule/task/Run/Attempt/Goal operations | **UNVERIFIED.** Existing tests cover admission, not physical work correlation under load. Profile lines 195–205 explain that the single raced schedule Run is cancelled without execution and sustained traffic has no schedules. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **UNVERIFIED overall, with contrary allowance evidence.** Executed actual-middleware test reproduces fresh allowance on the second instance. Local 429 enforcement and route backpressure regressions pass, not cluster-wide budget proof. |
| Complete telemetry and explicit thresholds | **UNVERIFIED.** Profile defines thresholds but acknowledges application-loop, detached-worker, saturation/reclaim and long-window gaps. Driver-loop and database probe latency are not complete production telemetry. |
| Kill/restart during active work proves drain/fencing/recovery | **UNVERIFIED.** No active physical-work drill executed. Boot and evaluator tests cannot establish loss/duplication-free recovery. |
| Long soak of exact RC artifact/configuration | **UNVERIFIED / BLOCKED.** `scripts/soak/run_soak.py:730` rejects host topology, even with sufficient duration. The historical evaluator fails both duration and artifact checks. No immutable promotion RC/configuration was supplied or selected. |
| Findings filed/reclassified at earliest broken milestone | **UNVERIFIED complete.** Historical notes are not completeness evidence. No GitHub mutations permitted or performed. |
| Machine/human evidence bound to exact image/package/commit/config hashes | **UNVERIFIED for RC.** Existing historical JSON/narrative fails artifact checks; this report is local validation evidence only. |

## Final disposition and handoff

**BLOCKED on production acceptance**, not on the dispatched schema failure or
Vulture scan. No source, test, inventory, or ledger change is justified by the
executed results. Only this report changes; no new tests means no inventory
count delta. No merge conflict exists, so no develop sync was attempted.

Next owner must select the immutable promotion artifact/configuration, resolve
the replica-selection requirement through the canonical security boundary,
complete the production-topology workload/telemetry, and run the required
long-window soak with physical-work and recovery correlation. Repeating the
obsolete CI failure or extending the host-only run cannot clear acceptance.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: production RC prerequisites}`.
The one assigned item is explicitly blocked; focused validation is complete.
Commit this report locally as handoff, not integration or promotion approval.
