# Issue #860 — bounded repair checkpoint (job 2d2f868d)

## Frozen scope

- One issue: #860; worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Verified starting HEAD: `32e82502d497fc9f9c32531286dc2e1616e57503`; clean on entry.
- Supplied comparison base: `2154f845347c9541016288c760f8da3f5cd2e064`.
- Inputs: supplied dispatch-context.json, prior result b3a66eed, and failure log
  98a11313/check-3.log. No check-*.log files were present in this job directory
  at entry. No GitHub enumeration or mutation.
- Inspection/validation files: repository instructions; docs/README.md;
  ADR-081626-f383, ADR-085, ADR-083026-a91e, ADR-082526-b36a,
  ADR-082826-08f0 (resolved from the supplied prior report);
  docs/testing/soak/m3a-load-profile.md;
  docs/testing/issue-860-b3a66eed-repair.md; scripts/soak/run_soak.py;
  tests/test_soak_promotion_gates.py; core persistence/pg_learnings.py and
  tests/persistence/test_pg_learnings.py; server api/tasks.py and adjacent
  concurrency tests; server api/rate_limit.py and main.py; relevant CI workflows
  and gate scripts.
- Permitted edits: this report; schema-fence test/source if the supplied failure
  reproduces; soak regression tests/source only for demonstrated failures;
  matching inventory note if tests change; quality/vulture-baseline.json only
  for actual reviewed findings from the requested scanner.
- Bounded adjacent validation: core tests/runs/test_execution_fencing.py and
  tests/graph/durable_runs/test_recovery_disposition.py (paths resolved by the
  supplied prior report).

## Initial evidence and assumption

The supplied old check-3.log reports 24 schema statements versus 21 expected.
The supplied previous result claims this was already repaired and identifies
missing exact-RC soak evidence and independent replica rate allowances. These
claims will be checked, not assumed. The large inherited base-to-head diff is
not this round's edit scope; no unrelated files will be removed or restored.
Assumption: this is the writer/CI-repair lane, not a read-only verifier lane.
No exact release-candidate ref or authorized deployed workload is supplied;
local tests cannot substitute for production soak acceptance.

## Fresh validation checkpoint

- Requested exact vulture command: PASS, 1323 reviewed identities / 1323
  findings, zero unclassified or never-allowlist findings. No actual scanner
  finding justifies a ledger amendment; ledger remains unchanged.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  PASS, 37 passed / 6 skipped. The supplied schema-fence failure does not
  reproduce. No speculative schema/test repair is warranted.
- Extracted all ten acceptance criteria from the supplied issue snapshot.
  Additional production-seam inspection and focused validation completed below.

## Validation executed in this round

Commands used 1000/1200-second timeouts; none used a full-tree pytest collection.

| Command | Outcome |
| --- | --- |
| `uv sync --locked --extra dev` | PASS, 256 resolved / 214 checked |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3277 files |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-core/tests/runs/test_execution_fencing.py packages/maistro-core/tests/graph/durable_runs/test_recovery_disposition.py -x -q` | PASS, 93 passed in 2.78 s |
| `uv run python scripts/check-deployment-claims.py` | PASS; checks component existence, not live deployment |
| `uv run python scripts/check-execution-lifecycles.py` | PASS, 19/19 classified/discovered |
| `git diff --check` | PASS |

Together with the separate persistence command: 130 passed, 6 skipped.
Vulture invocation matches `.github/workflows/quality.yml:1078` exactly.
No new tests, inventory deltas, ledger changes, or gate changes are warranted.

## Production evidence and ADR reconciliation

- `packages/maistro-core/tests/persistence/test_pg_learnings.py:175` already
  includes the three audit columns missing in the historical failure. Its
  assertion checks all 24 ordered statements; production `pg_learnings.py:215`
  takes the advisory lock inside the transaction before executing upgrades.
- `packages/maistro-server/src/maistro_server/main.py:648` installs
  `RateLimitMiddleware`; `api/rate_limit.py:93` constructs an independent
  `InMemoryRateLimiter`. The executed test
  `tests/test_soak_promotion_gates.py:439` sends the same identity to two such
  instances and observes `[200, 200, 429]` on each, both authenticated and
  unauthenticated. This is evidence of independent production-middleware
  allowances, not deployed load or a cluster-wide budget proof.
- `scripts/soak/run_soak.py:744` always rejects exact-RC equivalence for its
  host-process topology. Executed CLI regressions at
  `tests/test_soak_promotion_gates.py:103` reject synthetic four-hour evidence
  with missing/null/preflight artifact identity. Running that host emulator
  longer cannot satisfy the issue.
- Read accepted ADR-081626-f383, ADR-082526-b36a, ADR-082826-08f0, ADR-085,
  and ADR-083026-a91e. Canonical leases/reconciliation remain authoritative;
  stale-write rejection is not proof of unique physical work. Principal-keyed
  local enforcement does not waive the issue's replica-selection criterion.
  Missing telemetry cannot be called zero. No alternate Goal store, scheduler,
  event authority, authorization or execution path was introduced.

## All ten issue acceptance criteria

| Criterion | Fresh evidence and remaining gap |
| --- | --- |
| Representative RC load profile | UNVERIFIED. Read `docs/testing/soak/m3a-load-profile.md`; it explicitly lacks multi-user/Workspace, fan-out, successful tool/model, Design/Canvas and Goal/background-worker coverage. No selected RC applicability decision supplied. |
| Two application replicas | UNVERIFIED in deployed RC topology. Two ASGI instances exercise middleware and receipt routing, not two promoted images. |
| Sustained saturation, queue growth, reclaim, retries, leaks, restart | UNVERIFIED. Focused checks finish in seconds; no sustained production series generated. |
| No duplicate schedule/task/Run/Attempt physical work; Goal reconciliation | UNVERIFIED under deployed load. Fencing/recovery tests pass but bounded seam tests and admission identities are not this claim. |
| Rate/security/degradation cannot be bypassed by replica selection | NOT SATISFIED at the tested rate-limit seam: switching replicas obtains a fresh allowance. Deployed security/degraded behavior remains UNVERIFIED. |
| PostgreSQL/loop/worker/RSS/fd/queue/error telemetry with thresholds | UNVERIFIED. Profile thresholds exist but no fresh complete production series; driver loop latency cannot establish application loop latency. |
| Active-work replica kill/restart, drain/fencing/recovery | UNVERIFIED under deployed load; bounded canonical recovery tests passed only. |
| Long exact-RC/config soak, repeated after changes | UNVERIFIED. Current runner explicitly fails exact-RC artifact check, including synthetic four-hour CLI evidence. No immutable RC supplied. |
| Load findings classified before promotion | UNVERIFIED for completeness without representative load. Confirmed limiter gap is recorded here; no remote filing permitted. |
| Human/machine soak evidence tied to exact image/package/commit/config hashes | UNVERIFIED. This source-head validation report is not a production evidence pack. |

## Final handoff

**BLOCKED**: historical CI failure does not reproduce, and the requested exact
vulture ledger already matches the scan. No actual CI repair is available from
those inputs. Production acceptance remains unresolved; passing local checks
must not advance promotion.

Only this report changed. Next requires an immutable RC/configuration and
applicable representative workload, a decision/repair for the cluster rate-budget
prerequisite at the existing canonical seams, and a fresh exact-artifact soak
(profile minimum four hours) with complete metrics and physical-work recovery
observations. Redispatching the same historical CI failure cannot provide those
inputs. No GitHub mutation, push, destructive cleanup, or competing authority.

Progress: checked 1 issue; done 0 acceptance-complete; skipped 0 issues;
validation errors 0. This local report commit is a checkpoint, not integration
approval. Residual risks: unverified deployed behavior and inherited branch/base
integration differences, which were deliberately not changed in this round.
