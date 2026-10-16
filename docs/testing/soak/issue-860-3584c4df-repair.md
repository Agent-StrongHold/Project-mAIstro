# Issue #860 — bounded repair validation (3584c4df)

## Frozen scope

- Only issue #860, branch `auto-860`, starting HEAD
  `78057686eb715d918e19c745180a051d6e286914`, supplied develop base
  `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
- Worktree was clean; no incoming edits needed salvage. No GitHub mutations.
- Candidate edits: this report; `quality/vulture-baseline.json` only if the
  assigned exact-debt scan demonstrates a discrepancy. The actual scan passes,
  so no ledger or speculative production edits are justified.
- Validation scope: `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, `tests/test_prod_stack_boot_contract.py`,
  `packages/maistro-core/src/maistro/persistence/pg_learnings.py`, its adjacent
  persistence tests, `packages/maistro-server/src/maistro_server/api/tasks.py`,
  and `packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py`.
  Read-only architecture context: repository instructions, ADR registry,
  applicable execution/rate-limit ADRs, production deployment and load-profile docs.
- Supplied dispatch snapshot is the only issue/PR evidence source; no refetch or
  expansion to linked issues/PR repairs.

## Initial results and ambiguity

The role is writer/repair, not read-only verifier. No `check-*.log` files exist
in this job directory at initial inspection. The supplied older check-3 log
reports a schema-fence assertion of 24 statements versus 21 expected; whether
that failure persists is to be tested, not assumed from the prior result.

Executed the exact requested command:

`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`

PASS (exit 0): 1322 reviewed identities and 1322 findings, no unclassified or
never-allowlist findings. No ledger amendment is needed. The gate reports its
automatically resolved comparison base as `321cbdb8fe9b`; this is not silently
substituted for the lane's supplied develop base in acceptance claims.

## Fresh validation

- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  **37 passed, 6 skipped**. The historical check-3 failure does not reproduce;
  lines 174–176 already include the three validation audit columns. PostgreSQL
  integration cases were skipped, so this is not live concurrent-DDL proof.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  **81 passed**. Includes production-middleware independent replica allowances,
  production-router peer receipt 404, admission backpressure, process-group
  sampling, boot contracts and fail-closed artifact gates.
- `uv run ruff check .`: **PASS**.
- `uv run ruff format --check .`: **PASS**, 3301 files already formatted.
- Commands used 1200-second timeouts. Raw local logs:
  `/tmp/860-vulture.log`, `/tmp/860-3584-pg.log`, `/tmp/860-3584-soak.log`.

- `uv run python scripts/check-suite-inventory.py`: **PASS**, 17 suites,
  31323 unique identities, zero duplicate evidence. Log:
  `/tmp/860-3584-inventory.log`.
- `git diff --check`: **PASS**. The supplied develop base resolves locally.

No tests or runtime code changed; no inventory delta is warranted. Passing
static/unit checks is not a long-running exact-RC multi-replica soak.

## Architecture and acceptance reconciliation

Read `AGENTS.md`, the documentation authority map, accepted ADR-085 and
ADR-081626-f383, the production Compose topology, the load profile and adjacent
production/test code. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`.
ADR-081626-f383 assigns execution leases to the canonical Run store and explicitly
distinguishes stale-writer fencing from expiry takeover. Admission counts cannot
prove physical execution uniqueness or recovery. ADR-085 requires principal-keyed
rate enforcement; it is not evidence that the current process-local middleware
provides a shared budget. No scheduler, authorization, event or Goal authority was
added or changed to bypass these boundaries.

Fresh execution of `tests/test_soak_promotion_gates.py:439` reproduces the same
identity receiving `[200, 200, 429]` independently on two middleware instances
for both authenticated and unauthenticated cases. This agrees with
`packages/maistro-server/src/maistro_server/api/rate_limit.py:93`, which constructs
a per-instance `InMemoryRateLimiter`; it does not prove replica-selection-resistant
enforcement. The production-router probe at `tests/test_soak_promotion_gates.py:564`
observes an admitted receipt locally and a peer 404, consistent with the local
queue read in `packages/maistro-server/src/maistro_server/api/tasks.py:144`.
These are meaningful production-seam tests but are not deployed concurrency soaks.

`scripts/soak/run_soak.py:744` always marks its host-process preflight as not the
exact production Compose artifact. The CLI regression at
`tests/test_soak_promotion_gates.py:99` rejects missing/null/preflight artifact
evidence even with a synthetic four-hour duration. A longer run of this runner
cannot resolve that acceptance gap; disabling the gate would conceal it.

## Acceptance audit

| Issue criterion | Evidence and disposition |
| --- | --- |
| Representative RC load profile | UNVERIFIED: `m3a-load-profile.md` documents a preflight profile, but explicitly lacks concurrent users/Workspaces, Graph fan-out, successful model/tool calls, Design/Canvas and Goal/background workloads. RC-specific inclusion/exclusion is not established. |
| At least two deployed application replicas | UNVERIFIED: production Compose declares two replicas; this round executed two-instance ASGI probes, not a deployed production topology. |
| Sustained saturation, queue growth, reclaim, retry/backoff and leaks | UNVERIFIED: no sustained production series executed. Process-group sampler regression passing does not prove a leak-free application. |
| No duplicate physical work across schedule/task/Run/Attempt/Goal operations | UNVERIFIED: no production physical-work accounting or Goal reconciliation soak executed. Admission and schema-fence unit checks alone are insufficient. |
| Replica-resistant rate/security/degraded behavior | NOT PROVEN: fresh tests reproduce independent replica allowances. Canonical admission backpressure mapping passes; deployed security/degraded concurrency acceptance remains UNVERIFIED. |
| Required telemetry with explicit pass/fail thresholds | UNVERIFIED: documented thresholds are not fresh PostgreSQL/application-loop/process/RSS/FD/queue/error observations. Driver-loop latency is not application-loop latency. |
| Active-work kill/restart, drain/fencing/recovery | UNVERIFIED: no active-work production restart performed. |
| Long-running exact-RC/configuration soak | UNVERIFIED: no immutable promoted artifact/configuration selected and executed here; runner rejects artifact equivalence. Profile requires at least four hours. |
| Findings filed/reclassified to earliest broken invariant | UNVERIFIED for completion: no completed representative production run audited. No GitHub mutation performed; existing failures are recorded locally rather than silently waived. |
| Human/machine soak evidence tied to image/package/commit/config hashes | UNVERIFIED: this source-head validation record is not a hash-bound production soak evidence pack. |

## Disposition and next action

**BLOCKED**. Neither the supplied old schema failure nor an unbanked vulture
identity reproduces. There is no evidence-based CI repair to make in those files;
only this validation/handoff record changed. The prior production-acceptance
block is unresolved, not repaired by passing unit tests or more historical notes.

Next: designate an immutable RC/configuration, resolve the replica allowance
contract through the existing authorization architecture, provide representative
canonical-runtime workloads and application telemetry, then execute at least a
four-hour exact-artifact soak with active-work restart and physical-work accounting.
Any code/runtime-config changes require a new soak. Do not redispatch the same
stale check-3 or passing vulture scan as if it were an actionable source defect.

Progress: checked 1 issue; done 0 acceptance-complete; skipped 0 issues;
errors 0 in executed checks (6 explicitly skipped integration test cases).
Local commit is a blocked handoff only, not merge or release approval.
