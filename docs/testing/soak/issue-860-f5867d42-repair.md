# Issue #860 focused repair — f5867d42

## Frozen scope

- Only issue #860; assigned worktree `/home/dev/Git/wt/auto-860`, branch
  `auto-860`, starting HEAD `02f152a47280bbfe22cb70779c3e9ee13ee449bb`,
  supplied base `3c761d14db944a727fa0744444bc67cfe36d49f7` (both resolve).
- Initial worktree is clean; no salvage patch needed.
- Read-only evidence: supplied dispatch-context.json, prior result
  4030f4f4, prior check-3.log from 98a11313, repository instructions,
  relevant ADRs, existing soak runner/profile/promotion tests, pg_learnings
  implementation/tests, CI gate implementation/workflow.
- Candidate edits limited to this report, pg_learnings schema-fence test and
  corresponding inventory note if the reported regression reproduces, and
  quality/vulture-baseline.json only for scanner-confirmed reviewed identities
  under the explicit CI-repair exception. No other issue or PR processing.
- Current-job directory contains no check-*.log files. Prior check-3.log reports
  24 DDL statements versus a test expectation of 21; this is not yet reproduced.
- Assumption: writer repair role applies. Previous BLOCKED is an acceptance
  evidence gap, not a merge conflict; no develop sync is indicated.

## Progress

The historical schema failure does not reproduce: fresh `uv run pytest
packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` yields
**37 passed, 6 skipped** (PostgreSQL-dependent tests). The current expected DDL
already includes all three Gauntlet audit columns at lines 173–177. No repair
is justified from that stale log.

The exact requested vulture scan passes: **1323 reviewed identities / 1323
findings**, zero unclassified/never-allowlist findings. No ledger amendment is
justified; no identities were added or removed. The ten acceptance criteria
were extracted from the frozen dispatch issue body, not inferred from previous
results. No current-job driver logs were available.

Fresh validation also passes:

- `uv sync --locked --extra dev`: 256 resolved, 214 checked.
- `uv run ruff check .`: all checks passed.
- `uv run ruff format --check .`: 3270 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  **66 passed**. Includes authenticated and unauthenticated production middleware
  probes showing the same identity receives `[200, 200, 429]` independently on
  each replica (`tests/test_soak_promotion_gates.py:439`). Production installs
  that middleware at `maistro_server/main.py:648`.
- `uv run python -` importing the existing soak runner and evaluating retained
  `m3a-round43-shakedown.json`: asserts rejection of both `sustain_duration`
  (**420.09 seconds / 14400 minimum**) and `exact_rc_artifact`; also asserts
  `preflight_artifact_check()['ok'] is False`. PASS. Not a new soak.
- `uv run python scripts/check-doc-links.py`: 2657 Markdown files, zero broken
  relative links. `git diff --check`: PASS.
- Repeated the pg_learnings test after dependency sync: **37 passed, 6 skipped**.

## Architecture reconciliation

Read accepted ADR-085, ADR-081626-f383, ADR-082526-b36a and ADR-082126-f69c.
Retain `Goal -> Graph -> Run -> NodeRun -> Attempt`; recurrence creates canonical
Runs, and renewal/reclaim extends the original lease/fencing contract. No second
scheduler, execution authority or authorization path was introduced. ADR-081,
referenced by the load profile, is **Proposed**, not accepted deployment policy.
ADR-085 requires principal-keyed limits; the shipped middleware explicitly
implements process-local budgets (`api/rate_limit.py:31`, instantiated at line
93). Local enforcement is not proof of the issue's stronger replica-selection
non-bypass criterion. This mismatch requires resolution, not a waiver here.

## Acceptance assessment (all ten issue criteria)

| Criterion | Fresh evidence and remaining gap |
| --- | --- |
| Representative RC profile | **UNVERIFIED.** Inspected profile and `scripts/soak/run_soak.py:1373`: one credential, health/task/receipt/metrics mix; no representative Workspace population, Graph fan-out, successful model/tool, Canvas or Goal/background traffic. |
| At least two application replicas | **UNVERIFIED for deployed RC.** Tests exercise two production middleware instances, not two immutable RC deployments. |
| Sustained saturation/reclaim/backoff/leaks | **UNVERIFIED.** No fresh sustained deployment run; sampler unit tests cannot prove long-window behavior. |
| No duplicate physical work / Goal reconciliation | **UNVERIFIED.** Admission counters and canceled schedule probe Runs do not establish physical-effect uniqueness or sustained reconciliation. |
| Rate/security/degraded behavior immune to replica selection | **Contrary middleware evidence reproduced**, as above; complete RC behavior **UNVERIFIED**. |
| Full production telemetry and thresholds | **UNVERIFIED.** `run_soak.py:1410` measures driver loop lag, not application event-loop lag. No complete fresh production telemetry captured. |
| Active-work kill/restart drain/fencing/recovery | **UNVERIFIED.** Signal/rejoin logic inspected at `run_soak.py:1427`; no live physical-work recovery accounting executed. |
| Long exact-RC artifact/configuration soak | **UNVERIFIED.** `preflight_artifact_check` at `run_soak.py:730` always rejects host-preflight equivalence. Four hours of this runner would not satisfy artifact acceptance. |
| Findings filed/reclassified before promotion | **UNVERIFIED.** Supplied historical records are not new disposition evidence; no GitHub mutations performed. |
| Machine/human evidence tied to exact promotion hashes | **UNVERIFIED for RC.** Existing preflight evidence is not promoted-artifact proof; this report is validation evidence only. |

## Disposition

**BLOCKED**. No actual current schema-test or vulture failure warrants a repair.
Only this report changes; no new tests or inventory delta. Do not redispatch the
historical 21-versus-24 schema failure as a current defect. Required next input
is a selected immutable RC/configuration and a representative production-path
soak with complete telemetry, physical-effect/recovery accounting and resolution
of replica-budget semantics. No merge, push, remote mutation or gate weakening.

Checkpoint: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "RC selection and production soak acceptance evidence"}`.
Focused validation completed; issue acceptance remains blocked. Commit this
report locally as the required writer handoff. Existing branch-wide changes
were preserved, not reworked or represented as independently verified here.
