# Issue #860 — repair validation, job 86aff986

## Frozen scope and initial evidence

Only issue #860, branch `auto-860`, starting HEAD
`04e02961f0c39732b23f51469d78d490a64b0fc7`, supplied base
`435dc1937e0407ab4de198ffcced49860bb14ad2`. Starting worktree clean.
No remote operations or other issues are in scope.

Validation targets are `scripts/soak/run_soak.py`,
`tests/test_soak_promotion_gates.py`,
`packages/maistro-core/src/maistro/persistence/pg_learnings.py`,
`packages/maistro-core/tests/persistence/test_pg_learnings.py`,
`packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py`,
and the exact requested vulture gate. Edit surface: this report; conditional
repairs to those targets and `quality/vulture-baseline.json` only if fresh
failures justify them, with an inventory note for any test addition.

Inputs frozen to supplied dispatch-context.json, prior 3d741e30 result and
98a11313/check-3.log. Current job directory contains no check-*.log files.
The supplied failure is a schema test expecting 21 statements while receiving
24, not a vulture diagnostic. Prior passing claims will be checked afresh.

Ambiguity: assignment designates a source HEAD, not an immutable promotion
artifact/configuration. Do not assume the two are equivalent or label local
unit tests a release soak. Preserve Goal -> Graph -> Run -> NodeRun -> Attempt.

## Results

Fresh validation (both commands exited 0):

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: 1323 findings / 1323 reviewed identities;
  unclassified 0, never_allowlist 0. Gate selected base `4aa68edc0b6b`.
  No ledger amendment is justified by this result.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  103 passed, 6 skipped in 2.64 seconds. Supplied schema failure does not reproduce.
  Skips are not live database validation.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3270 files already formatted.
- `uv run python scripts/check-deployment-claims.py`: PASS (existence only).
- `uv run python scripts/check-merge-markers.py`: PASS.
- `uv run python scripts/check-backlog-consistency.py`: PASS, 168 items.
- `git diff --check`: PASS.

## Architecture and acceptance review

Read repository AGENTS.md, docs/README.md, accepted ADR-081226-69ee,
ADR-081626-f383, ADR-085, and proposed ADR-081. The accepted lease contract
explicitly does not define expiry takeover. Issue wording cannot authorize a
new reclaim scheduler. ADR-085 principal identity does not establish distributed
rate state. No execution, authorization or event authority was changed.

The current schema test independently includes the three Gauntlet columns at
`packages/maistro-core/tests/persistence/test_pg_learnings.py:171–175`; the stale
log omitted them. They match production pg_learnings.py:116–118. Existing tests
suffice for this no-code-change round; no inventory count delta.

Freshly executed `tests/test_soak_promotion_gates.py:439` runs two real production
RateLimitMiddleware instances: the same identity receives 200, 200, 429 from
each, while the first remains exhausted. Production middleware constructs a
process-local limiter at `packages/maistro-server/src/maistro_server/api/rate_limit.py:93`.
The server installs this middleware at main.py:648. This proves independent
allowances, not replica-selection non-bypass.

`scripts/soak/run_soak.py:730` deliberately returns failed exact-artifact evidence
for host-process preflight. No CLI override can turn duration into artifact
identity. `docs/testing/soak/m3a-load-profile.md:151–170` acknowledges missing
representative workloads and application-level telemetry. Historical bundles are
not fresh proof of this HEAD or a designated promotion artifact.
The executed CLI regression at tests/test_soak_promotion_gates.py:103 rejects
missing/null/preflight artifact records even with synthetic four-hour duration.
`deploy/docker-compose.prod.yml:11–12` explicitly calls itself a reference and
requires production digest pinning; it is not a supplied RC designation.
Artifact/configuration ambiguity is UNRESOLVED.

| #860 acceptance | Executed evidence / remaining gap |
| --- | --- |
| Representative release workload | UNVERIFIED: profile acknowledges absent concurrent Workspace/user, Graph fan-out, successful model/tool, Canvas/Design and background workloads. |
| Two deployed application replicas | UNVERIFIED: two in-process ASGI middleware instances tested, not deployed RC replicas. |
| Sustained saturation, queues, reclaim, retries and leaks | UNVERIFIED: focused tests are not sustained deployment observations. Expiry takeover must respect the accepted lease boundary. |
| No duplicated physical work | UNVERIFIED: admission/accounting tests do not establish physical Attempt uniqueness under multi-replica load. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | NOT PROVEN: production-middleware test reproduces independent allowances. Backpressure router test passes, not a distributed security soak. |
| Full telemetry and pass/fail thresholds | UNVERIFIED: no current RC telemetry; driver-loop measurements are not application-loop measurements. |
| Kill/restart during active work with drain/fencing/recovery | UNVERIFIED: no deployed active-work fault injection executed. |
| Long soak of exact promotion artifact/configuration | BLOCKED / UNVERIFIED: artifact/configuration not designated; runner is explicitly preflight-only. |
| Findings filed/reclassified | UNVERIFIED externally: local discrepancy documented, no new load run and no GitHub mutations. |
| Machine/human evidence bound to artifact/configuration hashes | UNVERIFIED for RC: current tests and this report are source-level evidence only. |

## Handoff

Only this report changed. No production, test, inventory, ledger, grant or gate
edits were warranted by current diagnostics. No merge conflict or uncommitted
salvage existed. All commands above ran in the assigned worktree; no push or
GitHub mutation occurred. The accumulated branch diff is not certified by these
focused checks.

Disposition: **BLOCKED**, not integration approval. The supplied CI failure is
stale; the exact-debt gate already passes. Repeating that repair cannot produce
release acceptance. Required next inputs/work: an immutable RC and runtime
configuration designation, representative production workloads and telemetry,
resolution of the replica-rate scope discrepancy through canonical security,
and a long exact-artifact run exercising active physical work and recovery.
Any subsequent code/runtime-configuration change requires another soak.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "RC designation and production-soak prerequisites"}`.

