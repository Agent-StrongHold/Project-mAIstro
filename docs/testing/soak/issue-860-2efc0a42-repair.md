# Issue #860 — repair checkpoint (job 2efc0a42)

## Frozen scope

- Only issue #860, branch `auto-860`, starting HEAD
  `2a57066afd081acd7996b115d854789d3291879b`, supplied base
  `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
- Starting worktree clean; no incoming diff to salvage.
- Inspect supplied dispatch snapshot and prior failure; no GitHub mutations.
- Files in validation scope: `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, core learning-schema implementation/test,
  server task admission implementation/test, relevant ADRs and quality gates.
- Only amend `quality/vulture-baseline.json` if the mandated scan identifies
  reviewed retained identities. Do not manufacture a ledger change.
- Job directory contained no `check-*.log` at start. Supplied historical
  `98a113.../check-3.log` reports 24 schema statements versus 21 expected;
  re-run current tests before deciding whether this still needs repair.
- Prior result is BLOCKED, not acceptance evidence. Exact release-candidate
  deployment identity and representative production inputs are not supplied;
  do not substitute synthetic ASGI probes for the requested long soak.

## Results

- Exact requested vulture command passed: 1322 findings / 1322 reviewed
  identities, zero unclassified. Resolved gate base `321cbdb8fe9b` differs
  from the supplied lane base. No ledger amendment justified.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  118 passed, 6 skipped (2.24 seconds). Historical schema failure does not
  reproduce: expected DDL already includes the three validation audit columns.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed (3301 files).
- Commands used 1200-second timeouts. No tests added or changed, so no inventory
  delta is needed.
- An initial dispatch-inspection helper assumed `issue` was an object rather
  than an integer and raised AttributeError; corrected extraction read the
  complete issue body from `sources`. This was not a product failure.
- `uv run python scripts/check-suite-inventory.py`: passed, 17 suites,
  31323 unique test identities, no duplicate evidence.
- `git diff --check`: passed.

## Reachable behavior and ADR reconciliation

Read repository instructions, documentation authority map, ADR-085 and accepted
ADR-081626-f383. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`.
The canonical Run store owns execution fencing. The lease ADR explicitly does
not define expiry takeover; a soak must not invent a competing reclaim authority
or claim admission uniqueness proves physical-work fencing.

Freshly executed `tests/test_soak_promotion_gates.py:439` instantiates production
`RateLimitMiddleware` and observes `[200, 200, 429]` independently on each of two
instances for the same identity (both authenticated and unauthenticated). This
matches the process-local limiter constructed at
`packages/maistro-server/src/maistro_server/api/rate_limit.py:93`. Per-principal
identity (ADR-085) does not itself establish a cluster-wide allowance. The
existing documented N-times-local-limit contract needs reconciliation with
#860's replica-selection acceptance, not a speculative ledger or auth change.

Freshly executed `tests/test_soak_promotion_gates.py:564` reaches the production
task router using queues sharing canonical admission and observes local 200 /
peer 404. `packages/maistro-server/src/maistro_server/api/tasks.py:144` reads the
local queue. This probe is meaningful negative evidence, not a deployed soak.

`scripts/soak/run_soak.py:744` explicitly rejects exact-RC equivalence for its
host-process runner. The executed promotion tests reject absent or false
artifact evidence even for synthetic long-duration data. Running this emulator
longer would not repair the missing exact-artifact requirement.

## Acceptance audit

| Criterion from supplied issue body | Executed evidence / remaining gap |
| --- | --- |
| Representative RC load profile | UNVERIFIED. `m3a-load-profile.md` explicitly lists missing multi-user/Workspace, fan-out, successful model/tool, Design/Canvas and Goal/background traffic. No selected-RC applicability decision supplied. |
| At least two deployed replicas | UNVERIFIED. Executed ASGI-instance probes, not a deployed production topology. |
| Sustained saturation, queues, expiry/reclaim, retries, leaks, restart | UNVERIFIED. No sustained production run this round; unit sampler checks do not establish these properties. |
| No duplicated physical work for schedules/tasks/Runs/Attempts/Goals | UNVERIFIED. No production physical-work accounting; admission counts cannot prove this. |
| Replica-resistant rate/security/degraded behavior | Not proven: fresh tests reproduce independent allowances and peer 404; backpressure tests pass. Deployed concurrency/security still UNVERIFIED. |
| PostgreSQL, application-loop, process/RSS/FD, queue/error telemetry and thresholds | UNVERIFIED. No fresh production metric series; driver-loop checks are not application-loop measurements. |
| Active-work kill/restart with drain/fencing/recovery | UNVERIFIED. No active-work production restart executed. |
| Long exact-RC/configuration soak and rerun after changes | UNVERIFIED. No designated immutable RC/configuration supplied or executed; host-process runner fails artifact equivalence. |
| Findings filed/reclassified to earliest broken invariant | UNVERIFIED for completion. Local blockers recorded; no completed representative run/classification audit and no GitHub mutations. |
| Machine/human evidence bound to image/package/commit/config hashes | UNVERIFIED. This source validation report is not a production soak evidence pack. |

## Handoff

**BLOCKED.** Historical schema-test and vulture discrepancies do not reproduce;
no evidence-based code/test/ledger repair is warranted. Only this report changed.
No inventory delta, new execution authority, deployment change, merge, push, or
GitHub mutation. Six skipped tests are not live PostgreSQL evidence.

Next: designate immutable RC/configuration and representative workload, reconcile
replica allowance/receipt behavior, then run the exact deployment for the profile's
four-hour minimum with production telemetry, active-work restart and physical-work
accounting. Re-dispatching the stale schema failure cannot resolve that blocker.

Progress: checked 1 issue; acceptance-complete 0; skipped issues 0; validation
failures 0 (one corrected inspection-helper error); next is the production-soak
prerequisites above. This local commit is a handoff only, not integration approval.
