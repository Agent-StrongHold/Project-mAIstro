# Issue #860 — repair checkpoint (231c402b)

## Frozen scope

- Only issue #860; assigned worktree `/home/dev/Git/wt/auto-860`.
- Starting HEAD `f8b3461ab9a2c47a7f7bc845ff5e6789617ec3f1`, supplied base
  `3c761d14db944a727fa0744444bc67cfe36d49f7`; both resolve locally.
- Initial tree clean; no uncommitted work to salvage.
- Inspect the supplied dispatch snapshot, prior result and cited check log;
  no GitHub refresh or mutations.
- Production/test inspection: `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, `docs/testing/soak/m3a-load-profile.md`,
  retained `m3a-round43-shakedown.json`, production rate middleware and wiring,
  and the prior log's specifically implicated schema tests.
- Run the exact requested vulture gate; only amend its ledger if fresh output
  identifies reviewed retained debt. No guessed scanner repair.
- Planned change is this evidence/handoff record; runtime/test/ledger edits only
  if those scoped checks demonstrate an actionable defect.

## Initial findings / ambiguity

The current job directory contains no `check-*.log` files. The supplied prior
result reports BLOCKED rather than a merge conflict. Assume this round requires
fresh gate and acceptance validation, not an unsolicited develop merge. The
supplied dispatch contains ten acceptance criteria; a passing unit suite is not
evidence of an exact-release-artifact multi-replica soak.

## Fresh validation (checkpoint)

`uv sync --locked --extra dev` passed. The exact requested vulture command
passed: 1323 reviewed identities, 1323 findings, zero unclassified and zero
never-allowlist findings. No ledger amendment is justified by actual output.

The cited prior `check-3.log` was read: schema test expected 21 DDL statements
but observed 24. Fresh reproduction does not fail: the current test explicitly
includes the three validation-audit columns in the ordered fence contract.

| Executed command | Outcome |
| --- | --- |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped; skips are not live database evidence |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 66 passed |
| `uv run ruff check .` | Passed |
| `uv run ruff format --check .` | Passed; 3270 files already formatted |
| `uv run python -` importing the actual driver and evaluating retained `m3a-round43-shakedown.json` | Asserted failed `sustain_duration` and `exact_rc_artifact`; 420.09 seconds observed against 14400 required; current preflight artifact check also false |

The last command is fresh evaluation of historical evidence, not a newly
executed soak. No deployed-RC load run was performed in this round.

## Architecture reconciliation

Read `AGENTS.md`, the documentation authority map and accepted ADR-085,
ADR-081626-f383, ADR-082126-f69c and ADR-082526-b36a. Scheduling produces
canonical Runs, not a parallel runtime; physical Attempt writes require fencing
and expired-lease recovery must distinguish dead from slow workers. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`. Receipt deduplication and process
rejoin are not substitutes for physical-work uniqueness/recovery observations.
ADR-085 requires principal-based rate identities; the current documented
process-local allowance does not establish #860's replica-selection non-bypass
criterion. No competing authorization or execution authority was introduced.

## Acceptance audit

All ten criteria from the supplied issue snapshot are covered below. Unit-test
success establishes tested mechanics only, not representative production load.

| Criterion | Evidence and disposition |
| --- | --- |
| Representative RC profile | **UNVERIFIED.** `run_soak.py:1373` uses one credential; the mix at 1381 is health/task/receipt/metrics traffic. The profile's remaining-gaps section identifies missing users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and Goal/background-worker reconciliation. |
| At least two application replicas | **UNVERIFIED for RC.** Passing middleware tests instantiate two ASGI apps, not two deployed immutable RC images. No fresh deployed run was executed. |
| Sustained saturation, queue growth, expiry/reclaim, retry/backoff, leaks and restart | **UNVERIFIED.** Historical sustain is 420.09 seconds; fresh evaluation rejects duration. Sampler regression tests do not establish long-window resource behavior. |
| Schedule/task/Run/Attempt/Goal physical-work uniqueness | **UNVERIFIED.** Driver probes at `run_soak.py:1496` run admission/occurrence races after sustain; receipt identity alone does not account for physical effects or sustained Goal reconciliation. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **Contrary allowance evidence reproduced.** `tests/test_soak_promotion_gates.py:439` passes for authenticated and pre-auth identities: each instance independently accepts two requests before 429. `api/rate_limit.py:95` creates an in-memory limiter per instance; production installs it at `main.py:648`. Full deployed security/degraded acceptance remains **UNVERIFIED**. |
| Complete PostgreSQL/app-loop/worker/RSS/fd/queue/error telemetry and thresholds | **UNVERIFIED.** `run_soak.py:1410` samples driver loop lag, not application loop lag. No complete fresh deployed-RC telemetry series was produced. |
| Kill/restart during active work proves drain/fencing/recovery | **UNVERIFIED.** Process kill/rejoin at `run_soak.py:1427` plus terminal Run counts cannot alone exclude physical loss/duplication. No active-work RC restart was executed. |
| Long soak of exact RC artifact/configuration | **UNVERIFIED.** Executed evaluator rejects retained duration and artifact identity. `run_soak.py:730` intentionally rejects host-process artifact equivalence, even at four hours. |
| Load findings filed/reclassified before promotion | **UNVERIFIED.** This local report records blockers; no fresh filing/reclassification completeness proof, and no GitHub mutations. |
| Machine/human evidence tied to image/package/commit/config hashes | **UNVERIFIED for RC.** Historical host-preflight evidence is not a current promoted-image/configuration proof. This report is validation evidence only. |

Final documentation validation: `uv run python scripts/check-doc-links.py`
passed (2661 Markdown files; zero broken links). `git diff --check` passed.

## Disposition

**BLOCKED** on representative, immutable-RC deployment and soak evidence, not on
the supplied stale schema failure or vulture scan. No ledger/source/test changes
are supported by those fresh checks. Only this report changes; no test inventory
delta is needed. The inherited branch diff remains preserved and is not approved
by these focused checks.

Next work requires selection of the RC image/configuration, a production-path
representative workload and complete telemetry/physical-effect accounting,
resolution of the replica-budget acceptance mismatch through the existing
security authority, then a new long exact-RC soak. Repeating host preflight or
adding ledger identities cannot resolve those prerequisites.

Checkpoint: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "immutable RC deployment and production soak evidence"}`.
