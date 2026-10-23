# Issue #860 — repair job 8d4b8b4d

## Frozen scope

One item: issue #860, branch `auto-860`, starting head
`8f8bb84ede0ed7f965c17bb713b3ea29e83c24c1`, supplied comparison base
`3c761d14db944a727fa0744444bc67cfe36d49f7`.
The worktree was clean; no incoming edits required salvage.
No GitHub mutations, ref refresh, or other issues are in scope.

Repair candidates are limited to the reported schema-fence regression in
`packages/maistro-core/tests/persistence/test_pg_learnings.py`, its production
module `packages/maistro-core/src/maistro/persistence/pg_learnings.py`, reviewed
identities emitted by the required vulture scan and
`quality/vulture-baseline.json` (only if the scan shows an actual mismatch),
an inventory note if tests change, and this report. Adjacent architecture,
soak harness, tests, and supplied dispatch evidence are read-only validation
inputs. No broad repair of inherited branch differences is authorized.

## Initial evidence and assumptions

- Assigned HEAD resolves exactly; worktree is clean.
- Current job directory has no `check-*.log` files. The supplied historical
  `98a11313.../check-3.log` reports 24 actual vs 21 expected schema statements.
  This is evidence to reproduce, not proof the current head still fails.
- Prior `891322a8.../result.json` says BLOCKED. Its acceptance claims must be
  checked against current code and fresh targeted validation.
- The inherited diff is large and includes unrelated deletions relative to the
  supplied base. Preserve it; this round does not integrate or approve it.
- No exact immutable RC/deployment target is specified in the assignment.
  Do not invent one or label a host-process smoke run production evidence.

## Fresh initial validation

- Required exact vulture command passed: 1323 findings, 1323 reviewed
  identities, zero unclassified. No ledger change is justified.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  -x -q` passed: 37 passed, 6 database-dependent skips. The historical failure
  does not reproduce. Lines 179–181 already expect all three audit columns;
  production `_EPISTEMIC_COLUMNS` declares them. Preserve the exact assertion.
- Logs: `/tmp/860-8d4b-vulture.log`, `/tmp/860-8d4b-schema.log`.

## Additional validation

All commands ran locally with 1200-second timeouts, not inferred from prior
jobs. Logs are `/tmp/860-8d4b-{sync,ruff,format,soak-tests,inventory,deployment}.log`.

| Command | Outcome |
| --- | --- |
| `uv sync --locked --extra dev` | PASS, 214 packages checked |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3270 files |
| `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs` | PASS, 74 passed |
| `uv run python scripts/check-suite-inventory.py` | PASS, 17 suites / 31128 unique identities / zero duplicate evidence |
| `uv run python scripts/check-deployment-claims.py` | PASS; component existence, not live deployment proof |

The initial schema suite and these tests total **111 passed, 6 skipped**.
No new tests or implementation changes were warranted; no inventory delta or
ledger amendment. Workflow commands were checked in `ci.yml`, `quality.yml`,
and `vulture-ratchet.yml`. No full-tree pytest claim is made.

## Architecture and reachable behavior

Read repository `AGENTS.md`, `docs/README.md`, accepted ADR-085,
ADR-081626-f383, and ADR-082526-b36a, plus adjacent production modules and tests.
The canonical Goal -> Graph -> Run -> NodeRun -> Attempt execution model remains
unchanged. The Run store owns the execution fence; the executor holds renewal.
The later lease ADR adds reclaim obligations, so the earlier ADR's boundary
cannot exempt recovery from soak acceptance. Admission deduplication is not
proof of fenced physical effects.

ADR-085 specifies per-principal rate identity. The current server installs
`RateLimitMiddleware` at `main.py:648`; the middleware constructs its own
`InMemoryRateLimiter` at `api/rate_limit.py:93`. The existing test at
`tests/test_soak_promotion_gates.py:439` actually exercises this production
middleware for both identity classes. Fresh execution confirms replica 1
returns `[200, 200, 429]`, then replica 2 also returns `[200, 200, 429]` for
the same identity. This matches the documented process-local implementation,
but does not establish #860's stronger replica-selection non-bypass criterion.
No second authorization path or new coordinated store was invented to reconcile
that contract gap. Owner resolution and production evidence are still needed.

## Acceptance audit

The ten criteria below are from the issue body in the supplied frozen
`dispatch-context.json`; linked PR/check statuses are not current proof.

| Criterion | Fresh evidence and disposition |
| --- | --- |
| Representative RC profile | **UNVERIFIED**. `m3a-load-profile.md:152` acknowledges missing concurrent users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and Goal/background work. `run_soak.py:1381` implements only the narrower health/task/receipt/metrics mix. No selected-RC applicability decision supplied. |
| At least two deployed application replicas | **UNVERIFIED**. Boot-contract and two-ASGI-instance tests passed; neither is a deployed exact-RC pair. No production deployment was exercised this round. |
| Sustained saturation, queues, lease reclaim, retry/backoff, memory/FD/process leaks and restart | **UNVERIFIED**. Real child-process sampler regression passed, but it is not sustained application traffic or a lease/reclaim experiment. |
| No duplicate physical work for schedules/tasks/Run/Attempt/Goal | **UNVERIFIED**. Admission-probe regression passed. `run_soak.py:1044` cancels the schedule probe's queued Run without executing it. No observable physical-effect oracle is provided for these operations. |
| Rate/security/degraded non-bypass under concurrency/replica selection | **UNVERIFIED as a whole; independent replica budgets observed**, as detailed above. Direct-path rejection tests and real task-ceiling backpressure pass, but do not prove cluster-wide non-bypass or all security/degraded behaviors. |
| Complete telemetry and explicit pass/fail thresholds | **UNVERIFIED**. Profile thresholds exist and sampler tests pass. `run_soak.py:1410` measures driver-loop lag, not application-loop lag. No fresh complete application/pool/query/lock/worker/queue/error/timeout time series judged against thresholds. |
| Kill/restart during active work with drain/fencing/recovery | **UNVERIFIED**. Boot cleanup and fail-closed gate tests pass; no active physical-work restart experiment executed. |
| Long unchanged exact RC artifact/configuration soak | **BLOCKED / UNVERIFIED**. No designated immutable RC/configuration supplied. `run_soak.py:730` rejects the host-process topology. Synthetic four-hour CLI cases passed by rejecting insufficient evidence; they are not four hours of traffic. |
| Findings filed/reclassified before promotion | Local dispositions recorded here: stale schema failure is non-reproducible; vulture has no mismatch; rate/evidence gaps persist. External filing/reclassification is **UNVERIFIED** and no GitHub mutation is permitted. |
| Machine/human evidence bound to image/package/commit/config hashes | **UNVERIFIED**. This report and local logs establish validation at the assigned head, not an exact-RC production soak bundle. |

## Handoff

**BLOCKED**, not merge-ready. Only this report changes. The inherited branch
and its unrelated differences remain preserved, not reviewed or approved for
integration. No current failing scanner identity or schema assertion justifies
code or ledger edits. Re-running the historical 21-versus-24 DDL failure cannot
resolve the promotion blocker.

Next actionable inputs: designate immutable RC image/configuration and the
applicable supported workload; resolve the replica-budget contract; implement
production physical-effect/recovery/application-telemetry evidence; execute the
unchanged RC for the profile's minimum 14400 seconds and publish a hash-bound
bundle. Docker unavailability is not asserted, and a local smoke deployment
would not substitute for those missing inputs.

Checkpoint: checked 1 issue, done 0 acceptance-complete issues, skipped 0
issues, errors 0 validation commands; 6 database-dependent tests skipped.
The local report commit is a writer handoff only, not integration approval.
