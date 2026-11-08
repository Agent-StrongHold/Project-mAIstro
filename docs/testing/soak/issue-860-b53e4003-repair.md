# Issue #860 repair checkpoint — b53e4003

## Frozen scope

- One item: issue #860, branch `auto-860`, starting HEAD
  `78a13598ccba69d9faf426f4f0cd54900f4c61fa`, supplied develop base
  `ab8b3737fa64f8d840f421ef87ca506c509444ff`.
- Worktree initially clean; no incoming edits to salvage.
- Inspect the supplied dispatch snapshot and previous failure, repository/ADR
  instructions, the learning-schema implementation/tests, soak runner/profile/
  evidence and adjacent tests. Execute the explicitly assigned vulture gate.
- Candidate edits limited to reproduced issue-related defects in those surfaces,
  their inventory note, this report, and reviewed vulture ledger identities if
  the assigned scan identifies any. No grants or unrelated fixes.
- No GitHub mutations, alternate execution authority, or RC promotion claims.

## Initial evidence and ambiguity

The supplied previous `check-3.log` failed the schema-fence test (24 statements
versus 21 expected). The current job directory contains no `check-*.log` files.
The previous result is BLOCKED on unproven exact-RC sustained load. These are
historical claims, not current validation. Proceed as writer/repair, reproducing
checks before changing code. No exact RC artifact/configuration is designated in
the assignment; local shakedown evidence will not be treated as promotion proof.

## Results

- Required vulture command passed: 1,322 findings, 1,322 reviewed identities,
  zero unclassified and zero never-allowlist findings. No ledger amendment is
  warranted; changing it would invent debt rather than repair the reported gate.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
  passed: 37 passed, 6 skipped. The reported 24-versus-21 failure does not
  reproduce: the starting tree already expects all three Gauntlet audit columns.
- `uv run ruff check .` passed.
- `uv run ruff format --check .` passed (3,301 files).
- Read accepted ExecutionRuntime and Attempt lease/fencing ADRs. Lease authority
  stays in the canonical Run store; its ADR explicitly does not promise expiry
  takeover. Admission uniqueness and process rejoin cannot stand in for physical
  Attempt recovery proof. No architectural reconciliation requires code changes.

- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`
  passed: 73 tests. Includes real production middleware on two ASGI instances,
  real task-router/spine backpressure, HTTP-probe negative cases, fail-closed
  artifact checks, and a live uv subprocess resource-sampling regression.
- `uv run pytest packages/maistro-server/tests -x -q` passed: 558 passed,
  8 skipped, 22 Starlette deprecation warnings. Skips are not acceptance proof.
- `uv run python scripts/check-suite-inventory.py` passed: all 17 suites,
  31,327 unique identities, no duplicate evidence. No tests were added or
  changed, so no inventory delta or baseline edit is needed.
- Executed the current `failed_promotion_checks` against the frozen sample
  `evidence/m3a-round30-shakedown.json` via `uv run python`: rejects
  `sustain_duration` and `exact_rc_artifact`. Observed duration is 420.08 s
  versus 14,400 s required, at historical HEAD `c4f45b309fd6`, not this HEAD.
  Also asserted the current runner's `preflight_artifact_check()['ok'] is False`.
  This re-evaluates historical evidence; it does not replay the historical load.

## Acceptance review (all ten criteria)

| Criterion | Executed evidence / remaining gap |
|---|---|
| 1. Representative RC profile | UNVERIFIED. Reviewed `m3a-load-profile.md:165`: one API key, missing concurrent users/Workspaces, fan-out, successful model/tool calls, Design/Canvas and sustained Goal reconciliation. Profile exists, but applicability to a designated RC is not established. |
| 2. At least two production application replicas | UNVERIFIED. Two real middleware instances are covered by executed tests, not deployed production replicas. `run_soak.py:744` explicitly identifies the runner as host-process preflight. |
| 3. Sustained load / saturation / leases / leaks | UNVERIFIED. Current evaluator rejects the sampled historical 420.08-second run against the 14,400-second minimum. No new sustained load run was executed. |
| 4. No duplicate physical work | UNVERIFIED. Admission oracle tests pass, but schedule probe cleanup cancels the queued Run without physical execution (`run_soak.py:1102`). Admission uniqueness is not Attempt uniqueness or recovery proof. |
| 5. Replica-independent security/degradation | NOT MET under a shared-budget interpretation. Executed `test_replica_selection_has_an_independent_production_allowance` for authenticated and unauthenticated identities: replica 1 returns 200,200,429; replica 2 gives another 200,200,429 for the same identity. This matches documented process-local policy (`rate_limit.py:32`), but does not prove the issue's non-bypass requirement. Full concurrent deployed security/degradation criterion remains UNVERIFIED. |
| 6. Complete production metrics and thresholds | UNVERIFIED. Live sampler test observes child RSS/descriptors; the sampler is process-group based and loop lag is driver-side, not application-loop latency (`m3a-load-profile.md:180`). No complete RC metric series was captured. |
| 7. Kill/restart during active work | UNVERIFIED. Historical process rejoin/exit is not correlated active Attempt drain/fencing/recovery. No new active-work restart was executed. |
| 8. Long soak of exact RC/config | UNVERIFIED. Current evaluator rejects the sampled evidence's artifact and duration gates. No immutable RC image/config was designated in this dispatch. A longer invocation of this preflight runner cannot satisfy this criterion. |
| 9. Findings disposition | UNVERIFIED at promotion grade. Local F1–F12 records exist in `m3a-soak-evidence.md`; no external filing or reclassification was performed or independently verified. GitHub mutations are prohibited. |
| 10. Hash-bound machine/human evidence | PARTIAL, overall UNVERIFIED. Historical JSON contains commit/config hashes and has a human report, but names a different commit and lacks proof of the exact promoted application image/config. No new RC evidence was published. |

## Disposition / handoff

**BLOCKED, not integration approval.** The reported schema-test and vulture
failures are already resolved in the starting tree; no evidence warrants a
production-code or ledger repair in this round. The only changed file is this
validation report. Existing production behavior and historical evidence are
preserved unchanged. No new test additions require an inventory note.

Next action requires a designated immutable RC artifact/configuration and an
exact-topology workload/measurement path covering the missing acceptance
surfaces, then a >=4-hour soak after code/runtime configuration is frozen.
Resolve the replica-selection budget requirement against documented per-process
policy without claiming local 429s prove a global budget. Do not retry the same
passing unit/ledger checks as a substitute for those prerequisites.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "RC prerequisites and production soak"}`.
Validation completed; issue acceptance remains blocked. Commit this report
locally; no push, issue closure, or GitHub mutation.
