# Issue #860 focused repair — a4593cbc

## Frozen scope

Assigned worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`, starting HEAD
`9d29f311b0522ba007c7e792a8503b77eb4b2891`, base
`ab8b3737fa64f8d840f421ef87ca506c509444ff`. Initial worktree clean.
Only #860 is processed; no remote mutations, ref changes or integration approval.

Frozen review/repair surfaces: the supplied dispatch snapshot and prior failed
check-3 log; repository instructions and execution/release ADRs;
`packages/maistro-core/src/maistro/persistence/pg_learnings.py` and its adjacent
`test_pg_learnings.py`; `scripts/soak/run_soak.py`,
`tests/test_soak_promotion_gates.py`, the documented `m3a-load-profile.md` and
`evidence/m3a-round30-shakedown.json`; task concurrency backpressure tests;
production rate-limit middleware; vulture checker, its CI invocation and
`quality/vulture-baseline.json` (only if fresh findings justify amendment).
This report records results. New tests, if justified, require an inventory note.

The current job directory has no driver check-*.log files. The supplied historical
check-3 log reports 24 DDL statements versus 21 expected. Current source already
includes the three Gauntlet validation-column expectations; reproduce before
editing. The prior result is BLOCKED and is not accepted as fresh evidence.

Ambiguity: writer repair is the assigned role, so verifier-only no-edit wording
is not applied. No immutable promoted RC artifact/configuration is designated in
the assignment. Do not substitute the preflight harness for production evidence.

## Validation

Fresh requested vulture invocation passed (exit 0): 1,322 findings, zero
unclassified and zero never-allowlist findings; 1,322 reviewed identities.
Invocation matches `.github/workflows/vulture-ratchet.yml:82-85`. No new retained
identities or eliminated findings justify a ledger amendment.

`uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
passed (exit 0): 37 passed, 6 skipped. The historical failure does not reproduce;
no schema/test repair is justified. The six skipped tests are not live database
acceptance evidence.

Additional fresh checks all exited 0:

- `uv run ruff check .` — all checks passed.
- `uv run ruff format --check .` — 3,301 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`
  — 73 passed.
- `uv run python scripts/check-suite-inventory.py` — 17 suites match; 31,327
  unique identities, no duplicate evidence.

No tests changed or added, so no inventory delta is needed.

An inline `uv run python` check imported the current runner and evaluated the
frozen `evidence/m3a-round30-shakedown.json`: exit 0, asserting both
`sustain_duration` and `exact_rc_artifact` are rejected. Observed duration is
420.08 seconds against the 14,400-second minimum. It also asserted the current
`preflight_artifact_check()` remains false. This is fresh evaluation of historical
evidence, not a fresh live soak.

## Architecture reconciliation

Reviewed accepted ADR-081426-1f7c (ExecutionRuntime contract) and ADR-081626-f383
(lease/fencing), the release contract in `ROADMAP.md`, the profile, runner and
adjacent tests. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt` and canonical
Run-store authority. Physical runtime identity is the Attempt ID; admission-only
Run counting does not prove physical execution uniqueness. The lease ADR does not
define expiry takeover, and `ROADMAP.md:78` explicitly defers task-queue restart
recovery. These boundaries require release-scope reconciliation, not an invented
scheduler/recovery authority or a claim that #860's broader criterion passed.

## Acceptance review

| # | Criterion | Evidence and disposition |
|---|---|---|
| 1 | Representative RC load profile | UNVERIFIED. `m3a-load-profile.md`, Remaining representative-profile gaps, explicitly omits concurrent users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and Goal/background workers. No selected immutable RC configuration supplied. |
| 2 | Two production replicas | UNVERIFIED. `scripts/soak/run_soak.py:744` identifies host-process preflight, not promoted production Compose. ASGI regression tests are not deployment proof. |
| 3 | Sustained saturation, leases, retry, leaks | UNVERIFIED. Fresh evaluator rejects the historical 420.08-second run against 14,400 seconds. No fresh sustained workload executed. |
| 4 | No duplicate physical work | UNVERIFIED. `scripts/soak/run_soak.py:1070` documents that the claim-probe Run never executes and is cancelled after admission. This cannot prove Attempt/Goal physical-work uniqueness. |
| 5 | Replica-independent rate/security/degraded behavior | UNVERIFIED overall. Executed `tests/test_soak_promotion_gates.py:439` reproduces separate allowances for the same authenticated and unauthenticated identity on two real middleware instances: each yields 200, 200, 429. Production installs this middleware at `packages/maistro-server/src/maistro_server/main.py:648`; `api/rate_limit.py:32` explicitly documents process-local budgets. No shared-principal budget proven. |
| 6 | Complete production metrics and thresholds | UNVERIFIED. Sampler tests pass, but the profile explicitly distinguishes driver-loop lag from application-loop lag and leaves worker/pool/reclaim coverage incomplete. No complete exact-RC series produced. |
| 7 | Active-work kill/restart/drain/fencing | UNVERIFIED. No live production Attempt restart executed. Process rejoin and terminal Run counts do not prove physical recovery. |
| 8 | Long soak of exact RC/configuration | UNVERIFIED. Current artifact check fails by design and historical evidence fails both artifact and duration checks. |
| 9 | Findings filed/reclassified before promotion | UNVERIFIED. Historical reports are not proof of current disposition; no GitHub mutations performed. |
| 10 | Human/machine evidence bound to promoted hashes | UNVERIFIED. Historical preflight artifacts do not establish a designated promoted image/configuration or qualifying run. |

## Handoff

**BLOCKED.** Only this report changed. No speculative production, test, gate or
ledger edits: the supplied failure does not reproduce and the required vulture
scan has no debt delta. This is an unresolved handoff, not integration approval.

Next: designate immutable promoted images/configuration; complete the supported
representative workload and production observability; reconcile replica-budget
and recovery semantics; execute the exact topology for at least four hours with
active Attempt kill/restart and fencing observations; publish hash-bound evidence
and disposition findings. Another identical vulture dispatch cannot supply those
prerequisites. No full-tree pytest or new live production soak was run.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "designated RC and production soak"}`.
This report is preserved in a local commit; no remote actions.
