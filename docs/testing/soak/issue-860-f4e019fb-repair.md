# Issue #860 repair checkpoint (f4e019fb)

## Frozen scope

Only issue #860; supplied head `0a40bbb7d541bc283c67592a62289780e0ec160d`
and develop base `e46ad6708fda20f76b8915679ef701f3ddb6b7e2`.
Repair the inherited merge conflict in `tests/test_ci_merge_group_scope.py`,
validate the reported learnings-schema regression, run the assigned vulture
per-identity gate and repair only evidenced findings, then validate the soak
acceptance paths. No GitHub mutations or new issue/PR enumeration.
Files eligible for focused changes: the conflict file, the evidenced learnings
schema test/implementation, reviewed vulture identities and ledger, and this
report plus inventory notes. Existing staged develop changes are preserved.

## Salvage / assumptions

The worktree arrived mid-merge: MERGE_HEAD resolves to the exact supplied develop
base, with one unmerged file. Unstaged and staged patches were preserved at
`/home/dev/Git/wt/incoming-860.patch` and `incoming-860-index.patch` before editing.
Finish this pinned merge rather than fetching a moving base (snapshot rule).
The current job directory contains no `check-*.log`; the supplied prior check-3
log reports 24 actual schema statements versus 21 expected in
`test_ensure_schema_fences_ddl_behind_advisory_lock`. Prior result is BLOCKED;
its acceptance claims are not treated as fresh evidence.

## Progress

- Snapshot and salvage complete. Conflict resolved using develop's test name
  and comment: both sides asserted identical wheel/docker selection and
  PostgreSQL exclusion; all assertions retained. No new test was added.
  Merged inventory accounting required a -1 overlap correction (see below).
- Read documentation authority map and accepted ADRs 081426-1f7c,
  081626-f383, 082526-b36a, and 073126-c4e1. Canonical execution ownership is
  unchanged; the later renewal/reclaim ADR extends the earlier fencing ADR.
  No unit test or host preflight can replace a soak of the selected immutable RC.
- `uv sync --locked --extra dev`: PASS.
- Prescribed vulture scan: PASS, 1,326 reviewed identities / 1,326 findings,
  zero unclassified or never-allowlist findings (`worker-vulture.log`). No
  scanner evidence justifies a ledger amendment; ledger remains untouched.
- Fresh schema suite: PASS, 37 passed / 6 PostgreSQL-dependent skips
  (`worker-schema.log`). Current independent expected-DDL list includes the
  three Gauntlet columns at `test_pg_learnings.py:175–177`; the reported
  24-versus-21 historical failure no longer reproduces. No speculative fix.
- Focused conflict/soak/production boot/backpressure/limiter tests: PASS,
  121 passed (`worker-focused.log`). Production limiter instances still grant
  independent `[200, 200, 429]` allowances to the same identity, as asserted in
  `tests/test_soak_promotion_gates.py:439–493`; direct enforcement does not
  prove a shared replica-independent budget.
- Whole-tree `uv run ruff check .` and `uv run ruff format --check .`: PASS
  (`worker-ruff-check.log`, `worker-ruff-format.log`).
- Ledger diff against both the pinned develop base and resolved local
  `origin/develop` is empty. No ledger rows were lost in the inherited merge.
- Merge-marker gate: PASS. Root-suite inventory initially failed: expected
  5,117, collected 5,116. Both merge parents added the same wheel-verifier
  regression under slightly different names; retaining one equivalent test
  needs an additive -1 overlap note. Added
  `inventory-notes/860-f4e019fb-merge-overlap.md`; rerun PASS: 5,116 expected
  and collected (`worker-inventory-final.log`).
- `git diff --check`: PASS. `git diff --cached --check`: exit 2 for a blank
  line at EOF in inherited develop file
  `docs/testing/inventory-notes/1109-hitl-pending-fairness.md:288`. Confirmed
  present verbatim in the pinned merge parent; preserved rather than making
  an unrelated cosmetic edit.
- Current evaluator applied to preserved round-30 JSON rejects both
  `sustain_duration` (420.08 s versus 14,400 s) and `exact_rc_artifact`.
  The runner's current `preflight_artifact_check()` also returns false
  (`worker-acceptance.log`). This is a fresh evaluation of historical evidence,
  NOT a newly executed soak.

## Commands and logs

Logs are under `/home/dev/maistro/jobs/f4e019fb6b764a13baf653b104b5d0af/`.
All validation commands used 1,200-second timeouts.

| Command | Outcome |
| --- | --- |
| `uv sync --locked --extra dev` | PASS |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; `worker-vulture.log` |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped; `worker-schema.log` |
| `uv run pytest tests/test_ci_merge_group_scope.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q` | 121 passed; `worker-focused.log` |
| `uv run ruff check .` | PASS; `worker-ruff-check.log` |
| `uv run ruff format --check .` | PASS, 3,195 files; `worker-ruff-format.log` |
| `uv run python scripts/check-merge-markers.py` | PASS; `worker-merge-markers.log` |
| `uv run python scripts/check-suite-inventory.py --suite tests/` | Initial -1 drift, corrected overlap note; PASS on rerun; `worker-inventory-final.log` |
| `uv run python -` importing the real soak evaluator and checking preserved round-30 evidence | PASS negative assertions for artifact and duration; `worker-acceptance.log` |
| `git diff --check` / `git diff --cached --check` before final staging | PASS / inherited EOF whitespace warning described above |

## Acceptance checked against reachable behavior

| #860 criterion | Evidence and remaining boundary |
| --- | --- |
| Representative RC profile | **UNVERIFIED complete.** `m3a-load-profile.md:145–160` admits missing users/Workspaces, Graph fan-out, tool/model success, Design/Canvas and Goal/background work. `run_soak.py:1382–1395` executes only health/task/read/metrics traffic with one credential. |
| At least two application replicas | **UNVERIFIED deployed RC.** Production Compose defines two services; boot-contract tests pass, but they do not execute the selected release deployment. No new deployment soak was run. |
| Sustained saturation, queue growth, expiry/reclaim, retries, leaks, restart | **UNVERIFIED.** Historical 420.08-second run fails the 14,400-second minimum; fresh sampler unit/subprocess tests are not long-window workload observations. |
| No duplicate physical work / Goal reconciliation | **UNVERIFIED.** `run_soak.py:1044–1072` cancels the schedule probe Run without execution; `1075–1169` proves only an admission race. No sustained physical Attempt or Goal reconciliation oracle was executed. |
| Rate/security/degraded behavior without replica-selection bypass | **UNVERIFIED as stated; shared-budget interpretation falsified.** Executed `test_replica_selection_has_an_independent_production_allowance` for authenticated and unauthenticated identities. Same identity receives `[200,200,429]` independently from each production middleware instance. `rate_limit.py:32–37` explicitly documents process-local budgets; no competing authorization path was introduced to conceal this mismatch. |
| Full telemetry and explicit thresholds | **UNVERIFIED complete.** `run_soak.py:500–536` observes process groups, PG probe latency/connections/waiting locks and Run statuses; `1420–1430` measures driver rather than application loop lag. Root tests exercise sampler completeness but not application-loop latency, detached workers or long-window pool/queue/leak thresholds. |
| Kill/restart during active work, drain/fencing/recovery | **UNVERIFIED.** `run_soak.py:1436–1489` signals/restarts a process group and counts HTTP outcomes; no fresh active-Attempt fencing/recovery evidence in this round. A process rejoining does not establish absence of duplicate/lost physical work. |
| Long soak of exact RC/configuration | **BLOCKED / UNVERIFIED.** `run_soak.py:730–741` always rejects host preflight as exact-RC evidence. Current evaluator rejects the historical artifact and duration; no selected immutable RC/configuration was validated. ADR-073126-c4e1 prevents treating this merge's code/configuration as equivalent to old evidence. |
| Findings filed/reclassified at earliest invariant | **UNVERIFIED completeness.** Existing evidence pack records named findings, but no external filing/reclassification was performed or independently validated; GitHub mutations are prohibited. |
| Machine/human evidence tied to exact hashes | **UNVERIFIED for candidate.** Preserved round-30 evidence records historical `c4f45b309fd622f2e8a4b315dad35e721d81aad3` and hashes, not this merged tree or a selected RC image/configuration. `collect_hashes` at `run_soak.py:1176–1212` cannot certify the production image. |

## Handoff / residual risks

Focused changes are `tests/test_ci_merge_group_scope.py`,
`docs/testing/inventory-notes/860-f4e019fb-merge-overlap.md`, and this report.
All inherited staged develop changes are preserved by completing the existing
merge; they are not new unrelated implementation work. The merge's full staged
file list is retained in `worker-commit-files.log` in the job directory.
No production behavior or quality/grant ledger was edited in this repair.
No new tests were needed for the equivalent-test conflict resolution; existing
meaningful regressions were executed without weakening their assertions.

**Verdict: BLOCKED for #860 acceptance, not a CI-repair failure.** The supplied
conflict is resolved, the stale schema failure did not reproduce, the scanner
supplies no repairable debt, and inventory is reconciled. Remaining work is a
representative, instrumented, active-work recovery soak of an owner-selected
immutable RC/configuration, including resolution of the rate-limit contract
mismatch through existing canonical seams. Do not restart this lane merely to
repeat a passing vulture scan or add another short host preflight.

Focused tests do not validate all incoming develop features; six live-PostgreSQL
schema cases were skipped. The inherited whitespace warning is explicitly
preserved. No four-hour soak, selected image deployment or GitHub action is
claimed. Final local commit completes the merge and checkpoints this handoff.

Progress: {checked: 1, done: 0, skipped: 0, errors: 0, next: selected-RC acceptance soak}.
The one assigned issue was checked; its CI repair is complete but its acceptance
is not done.
