# Issue #860 repair — job 45bb4e51

## Frozen scope

- Assigned issue: #860 only, worktree `/home/dev/Git/wt/auto-860`.
- Starting HEAD: `2124456357340b34f418a56694d9ecad71578a9e` (resolved); supplied base: `2154f845347c9541016288c760f8da3f5cd2e064` (resolved).
- Clean starting worktree; no incoming edits to salvage.
- Inspect existing #860 soak harness/tests, schema-fence production implementation/tests, relevant ADRs and CI gate definitions.
- Candidate edits limited to `packages/maistro-core/tests/persistence/test_pg_learnings.py`, its production implementation if the reproduced failure requires it, `quality/vulture-baseline.json` only for observed reviewed identities, an inventory note if needed, and this report.
- Evidence inputs: supplied dispatch snapshot, prior result e025f198, prior check-3.log from job 98a11313. No new GitHub enumeration or mutations.

## Initial evidence and ambiguity

The supplied job directory has no check-*.log files. The supplied prior log shows
24 schema statements versus 21 expected; reproduce before choosing a repair.
The prior result is BLOCKED on exact-RC production evidence. Assumption: this
round repairs demonstrated CI failures, but cannot claim release acceptance
from unit tests or host preflight. Existing unrelated inherited work is preserved.

## Reproduction checkpoint

- Exact vulture command passed: 1,323 findings / 1,323 reviewed identities,
  zero unclassified and zero never-allowlist. No ledger amendment justified.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  37 passed, 6 skipped in 1.56 seconds. The supplied historical failure does not
  reproduce. The test already includes all three Gauntlet audit columns at
  lines 175–177, matching production `_EPISTEMIC_COLUMNS`.
- No speculative production or test change is warranted by this evidence.

## Focused validation

All validation commands used a 1,200-second timeout.

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; 1,323 reviewed identities, no new debt |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped; no live PostgreSQL evidence claimed |
| `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs` | 81 passed in 2.37 s |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS; 3,277 files |
| `uv run python scripts/check-doc-links.py` | PASS; 2,710 Markdown files, zero broken links |
| `uv run python scripts/check-backlog-consistency.py` | PASS; 168 items |
| `git diff --check` | PASS |

The exact vulture arguments match `.github/workflows/quality.yml:1078–1081`.
No tests were added or changed, so no suite inventory delta is needed.

## Architecture and reachable behavior

Read repository instructions, the documentation authority map, Accepted ADR-085
and ADR-082826-b601, and Proposed ADR-081. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`; no separate consumer, execution,
authorization or event authority was introduced. Proposed deployment language
and the preflight's scope exclusions do not waive issue acceptance. The canonical
consumer ADR requires execution through the existing NodeRun/Attempt spine;
admission-only evidence cannot substitute for physical-work evidence.

Fresh inspection and executed regression evidence:

- `scripts/soak/run_soak.py:744`: `preflight_artifact_check` returns `ok=False`.
  `tests/test_soak_promotion_gates.py:106` exercised the CLI rejection for missing,
  null and preflight artifact records despite a synthetic four-hour duration.
- `scripts/soak/run_soak.py:1067`: `_terminalize_probe_run` cancels the queued Run;
  its admission racers never execute it. This cannot prove no duplicate work.
- `packages/maistro-server/src/maistro_server/api/rate_limit.py:93`: each middleware
  constructs an `InMemoryRateLimiter`. The executed production-middleware test
  at `tests/test_soak_promotion_gates.py:439` observes `[200, 200, 429]` on each
  instance for the same authenticated/anonymous identity. Direct-replica local
  enforcement does not establish a cluster-wide allowance.

## Acceptance disposition

| #860 criterion | Evidence / disposition |
| --- | --- |
| Representative RC workload | **UNVERIFIED**. Inspected `m3a-load-profile.md`: one-key degraded-path preflight, not representative users/Workspaces, Graph fan-out, successful model/tools, Design/Canvas or background reconciliation. |
| Two production replicas | **UNVERIFIED**. Two ASGI limiter instances are not two deployed RC replicas. |
| Sustained saturation, queue growth, lease reclaim, retries, memory/descriptor/process leaks | **UNVERIFIED**. Short regressions and the real child-process sampler test do not supply a sustained production series. |
| No duplicate physical schedule/task/Run/Attempt work; Goal reconciliation | **UNVERIFIED**. The schedule probe admits then cancels without physical execution. |
| Rate/security/degraded non-bypass under replica selection | Independent production-middleware allowances reproduced; deployment-level non-bypass remains **UNVERIFIED**. |
| Complete telemetry and explicit thresholds | **UNVERIFIED**. Sampler regressions passed; no live RC database/worker/application-loop series captured. Driver-loop lag is not application-loop lag. |
| Kill/restart during active work with drain/fencing/recovery | **UNVERIFIED**. No production kill/restart experiment executed. |
| Long-running exact-RC soak | **UNVERIFIED**. Existing host-process runner fails exact-artifact equivalence irrespective of duration. |
| Findings classified to earliest milestone invariant | Backlog consistency gate passed (168 items); production completeness **UNVERIFIED**. No GitHub mutations authorized or performed. |
| Machine/human evidence tied to image/package/commit/config hashes | **UNVERIFIED**. This is a source-validation report, not a hash-bound production-soak bundle. |

## Handoff

**BLOCKED**, not integration approval. The cited CI failure is already repaired;
there is no observed vulture debt to amend. Repeating the stale schema log does
not provide an actionable repair. Remaining work needs an explicitly selected
immutable RC artifact/configuration, representative production workload,
physical-work/recovery oracles, complete telemetry and a qualifying long soak.
The replica-selection allowance claim must also be resolved. A longer host
preflight cannot meet the artifact criterion.

Changed file: this report only. All inherited code, tests, ledgers and evidence
are preserved; this focused check does not certify the broad inherited diff.

Progress: checked 1 issue; acceptance-complete 0; skipped 0 issues; command
errors 0. Next: production acceptance work, not speculative gate/test changes.
