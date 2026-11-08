# Issue #860 — repair job f5c5b9da

## Frozen scope and initial checkpoint

- Only issue #860; assigned worktree `/home/dev/Git/wt/auto-860`.
- Starting HEAD verified: `394b1e68274c8a873c0e7d57e5d174e42096dfc0`; clean working tree.
- Supplied base: `2154f845347c9541016288c760f8da3f5cd2e064`.
- Evidence: supplied dispatch-context.json, prior result 45bb4e51, historical
  job 98a11313/check-3.log. No current check logs were supplied.
- Frozen candidate edit scope: this report, the existing pg_learnings schema
  fence implementation/test if the cited failure reproduces, soak runner and
  promotion tests if a concrete bounded repair is demonstrated, associated
  inventory note if tests change, and quality/vulture-baseline.json only for
  observed reviewed identities under the explicit CI-repair authorization.
- No GitHub mutation, ref enumeration, or unrelated inherited change repair.

Historical log reports 24 schema statements versus 21 expected. Prior report
claims it is already fixed; that claim is not accepted without fresh validation.
Assumption: repair demonstrated CI problems; do not label host preflight or
unit tests as production RC soak evidence. Exact release artifact selection and
production acceptance may remain blocked independently of CI.

## Reproduction checkpoint

Fresh exact vulture invocation passed: 1,323 findings / reviewed identities,
zero unclassified and zero never-allowlist. No ledger amendment is justified.
The referenced historical schema failure did not reproduce:
`uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q -rs`
returned 37 passed, 6 skipped (no migrated PostgreSQL DSN configured).
No source or test repair is justified by that historical log. The current test
at `packages/maistro-core/tests/persistence/test_pg_learnings.py:175–177`
already lists the three Gauntlet columns missing from the historical expectation.
Production `pg_learnings.py:215–222` guards the upgrades with a transaction and
advisory lock; the passing test checks the complete ordered body independently.

## Fresh focused validation

Each validation command used a 1,200-second timeout.

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; 1,323 reviewed identities, zero new findings; matches quality.yml:1078–1081 |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q -rs` | 37 passed, 6 PostgreSQL-dependent skips |
| `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs` | 81 passed |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS; 3,277 files |
| `uv run python scripts/check-doc-links.py` | PASS; 2,711 Markdown files, zero broken links |
| `uv run python scripts/check-backlog-consistency.py` | PASS; 168 items |
| `git diff --check` | PASS |

No tests were added or changed; no inventory delta is required. These results
are source/regression validation, not a deployed multi-replica experiment.

## Architecture and acceptance evidence

Read repository instructions, the documentation authority map, Accepted ADR-085
and ADR-082826-b601, and Proposed ADR-081. Accepted consumer semantics require
physical execution through the existing NodeRun/Attempt spine; admission-only
probes cannot substitute for execution evidence. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`. No new scheduler, store,
authorization or event authority is introduced. The Proposed deployment ADR
and existing preflight exclusions do not waive #860 acceptance.

The inspected production reference Compose file declares two server replicas,
PostgreSQL primary/replica, Redis, shared storage and a required external model
gateway. It is a reference build, not a supplied immutable RC selection.

| #860 acceptance criterion | Executed evidence / disposition |
| --- | --- |
| Representative RC load profile | **UNVERIFIED**. Inspected `m3a-load-profile.md`: one-key degraded-path mix explicitly lacks users/Workspaces, Graph fan-out, successful model/tool, Design/Canvas and Goal/background-worker coverage. |
| At least two production application replicas | **UNVERIFIED**. Compose declares two replicas; ASGI middleware regression instances are not deployed RC replicas. |
| Sustained saturation, queue growth, lease reclaim, retries and leak observations | **UNVERIFIED**. Short regression tests do not establish a long production time series. |
| No duplicate physical schedule/task/Run/Attempt work; Goal reconciliation | **UNVERIFIED**. `scripts/soak/run_soak.py:1067` cancels the admitted schedule probe without executing it. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | Production middleware counterexample reproduced by `tests/test_soak_promotion_gates.py:439`: same identity gets `[200, 200, 429]` independently on each replica. Deployment non-bypass remains **UNVERIFIED**; `rate_limit.py:93` constructs process-local state. |
| Complete PostgreSQL/application-loop/worker/resource/queue/error telemetry and thresholds | **UNVERIFIED**. Sampler tests passed, but no production series captured; driver-loop latency is not application-loop latency. |
| Kill/restart during active work proves drain/fencing/recovery | **UNVERIFIED**. No production active-work restart experiment performed. |
| Long-running exact-RC soak | **UNVERIFIED**. `run_soak.py:744` rejects host preflight as exact-artifact evidence; executed CLI tests at `tests/test_soak_promotion_gates.py:106` reject missing/null/preflight artifact records even at synthetic four-hour duration. |
| Load findings classified to earliest broken milestone invariant | Backlog consistency passed; production completeness **UNVERIFIED**. No new load experiment or GitHub mutation performed. |
| Machine/human evidence bound to exact image/package/commit/config hashes | **UNVERIFIED**. This report is not a production soak evidence bundle. |

## Final handoff

**BLOCKED** on production acceptance, not on the cited schema failure or the
vulture gate. No speculative ledger amendment or cosmetic source repair was
made. Only this report changed; all inherited implementation and evidence are
preserved. The broad inherited branch diff is not certified by focused checks.

Next required inputs/work: select the immutable RC image/configuration and
representative workload, resolve the replica-selection allowance contract,
exercise physical-work and recovery oracles through canonical execution,
capture complete production telemetry, then run and publish a qualifying
long-duration soak. Repeating a historical fixed schema failure cannot resolve
these acceptance gaps. No integration approval or issue closure is implied.

Progress: checked 1 issue; acceptance-complete 0; skipped 0 issues; validation
errors 0. Local report commit is the checkpoint for this round.
