# Issue #860 bounded repair — job 5f3a18a8

## Frozen scope

Only issue #860, branch `auto-860`, starting HEAD
`b98173447562f98cfb231c8b00bc3f0b19446496`, supplied develop base
`3c761d14db944a727fa0744444bc67cfe36d49f7`.
Initial worktree clean; no salvage needed. No remote mutations.

Process the supplied schema-fence failure and explicit vulture gate, then
validate the existing promotion tests/evidence. Candidate edits are limited to
`packages/maistro-core/tests/persistence/test_pg_learnings.py`, its production
`pg_learnings.py` if reproduced evidence requires it,
`quality/vulture-baseline.json` only for actual reviewed scanner findings,
`tests/test_soak_promotion_gates.py`, `scripts/soak/run_soak.py`, a corresponding
inventory note if tests change, and this report. Architecture and adjacent
files are read-only context. No re-enumeration of remote issues/PRs.

## Initial evidence / assumptions

The job directory contains no driver `check-*.log` files. The supplied prior
`98a113.../check-3.log` records 24 DDL statements against 21 expected in the
schema fence test. The prior result `bc73452.../result.json` says BLOCKED;
that is a claim to revalidate, not acceptance evidence. Assume this round is a
writer repair, as explicitly assigned, not a read-only verifier.

Exact RC identity/configuration is not supplied in the dispatch assignment;
no guessed deployment or artifact will be called promotion evidence.

## Validation

Fresh exact vulture command passed: 1323 reviewed identities / 1323 findings,
zero unclassified or never-allowlist findings. No ledger amendment is warranted.
`uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
passed (37 passed, 6 skipped). Current test already includes all 24 DDL
statements, including the three validation-audit columns absent from the old
failure. The reported failure is not reproducible on the assigned HEAD.
No code/test edit is justified by these two checks.

Additional commands executed successfully:

- `uv sync --locked --extra dev`: checked 214 packages.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: 66 passed.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: 3270 files already formatted.
- `uv run python -`: imported the actual soak module and evaluated retained
  `evidence/m3a-round43-shakedown.json`; observed `sustain_seconds=420.09`,
  failures `sustain_duration` and `exact_rc_artifact`. Asserted both failures
  and `preflight_artifact_check()['ok'] is False`. This is reevaluation of
  historical evidence, not execution of a new soak.

## Architecture and acceptance audit

Read accepted ADR-085, ADR-081626-f383, ADR-082126-f69c and
ADR-082526-b36a, plus the repository instructions/documentation map. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`: schedules produce canonical Runs,
the canonical store owns fencing, and recovery depends on expired liveness,
not restart-implies-death. No competing authority or policy waiver added.
ADR-085's per-principal requirement does not turn process-local rate enforcement
into proof of #860's stronger replica-selection criterion.

| Criterion | Executed evidence / remaining gap |
| --- | --- |
| Representative RC workload | **UNVERIFIED.** Read `m3a-load-profile.md`; its remaining-profile-gaps section explicitly lacks concurrent users/Workspaces, Graph fan-out, successful model/tool calls, Design/Canvas and Goal workers. Confirmed driver `scripts/soak/run_soak.py:1373` uses one key and `:1381` only the limited HTTP mix. |
| At least two deployed replicas | **UNVERIFIED for RC.** Two ASGI instances in unit tests are not a deployed RC topology. No new load deployment executed. |
| Sustained saturation/reclaim/backoff/leak/restart observations | **UNVERIFIED.** Executed evaluator rejects retained 420.09-second evidence; profile minimum is 14400 seconds. |
| Schedule/task/Run/Attempt and Goal physical-work uniqueness | **UNVERIFIED.** Driver `:1496` runs admission probes after sustained traffic; uniqueness of admission and terminal counts is not physical-effect accounting. |
| Security/degraded behavior and replica-selection non-bypass | **UNVERIFIED overall; contrary rate-allowance evidence reproduced.** Executed `tests/test_soak_promotion_gates.py:439` for authenticated and pre-auth clients: each instance permits `[200, 200, 429]` for the same identity. Confirmed production `main.py:648` installs this middleware and `api/rate_limit.py:95` constructs its own in-memory limiter. |
| Complete telemetry with thresholds | **UNVERIFIED.** Driver `:1410` measures driver-loop lag, not application-loop lag; no exact-RC telemetry series captured. |
| Active-work kill/restart drain/fencing/recovery | **UNVERIFIED.** Driver `:1427` signals/restarts the process and records availability, not physical-effect conservation. Passing probe unit tests cannot supply live recovery evidence. |
| Long soak of exact RC/configuration | **UNVERIFIED.** Executed artifact check at `:730` rejects host-process equivalence; historical evaluator rejects duration and artifact identity. No immutable RC/config supplied for this round. |
| Findings filed/reclassified to earliest invariant | **UNVERIFIED.** No full disposition audit or remote mutations performed. Local report records blockers only. |
| Machine/human evidence bound to exact hashes | **UNVERIFIED for RC.** Existing preflight evidence and this report are not a hash-bound production RC soak. |

## Disposition and handoff

**BLOCKED**, not merge-ready. Reported deterministic failure is stale on the
assigned HEAD; the requested vulture scan has no identities to amend. No merge
conflict exists. Changing code or a ledger merely to generate a repair diff
would not address actual evidence.

Only this report changed. No test addition/change, so no inventory delta is
needed. Existing source, tests, ledgers and soak evidence remain preserved.
No new soak was run; the six PostgreSQL-gated skips are not acceptance evidence.

Next: provide the selected immutable RC/config and complete representative
workload; resolve the replica-allowance acceptance gap with the security owner;
run the production topology for the required duration with application telemetry
and physical-effect/fencing/recovery accounting. Repeating this same CI repair
or extending the host preflight cannot satisfy the exact-artifact requirement.

Checkpoint: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "selected RC, representative workload and production soak"}`.
Local report commit is a blocked handoff only, not integration approval.
