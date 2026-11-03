# Issue #860 repair — job 5f5443a5

## Frozen scope

- Issue: #860 only; worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD: `6dde09f5ef7244bd7381add0d6e4d156ed820b6b` (resolved, clean).
- Assigned base: `435dc1937e0407ab4de198ffcced49860bb14ad2`.
- Inputs: this job's `dispatch-context.json`, supplied prior result and failed log.
- Validation scope: soak harness/profile/evidence and adjacent tests; production
  rate limiting and relevant execution ADRs; exact vulture gate, ruff and inventory.
- Edit scope: this report; only evidence-backed repairs to those surfaces, plus
  `quality/vulture-baseline.json` if the explicit CI-repair scan requires it.
- No GitHub mutations, background commands, scheduler or authorization changes.

## Initial observations

The starting worktree is clean. No `check-*.log` files exist in this job directory.
The supplied prior result reports incomplete promotion evidence; its claims are
not treated as current validation. Writer role is assumed from the explicit
repair assignment. Validation results and remaining acceptance gaps follow below.

## Checkpoint 1

- Exact requested vulture command passed: 1,323 reviewed identities / 1,323
  findings, no unclassified or never-allowlist findings. No ledger edit justified.
- The supplied historical `check-3.log` failed the learning-schema advisory-lock
  test (24 actual DDL statements versus 21 expected). Current rerun pending.
- The load profile explicitly limits the host harness to preflight, requires
  14,400 seconds and exact Compose artifact identity for promotion, and documents
  unverified representative workload/physical-fencing surfaces. No duration or
  artifact bypass will be introduced to make this lane appear complete.

## Checkpoint 2

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed (3,270 files).
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py -x -q`:
  102 passed, 6 skipped. The historical schema test failure is not reproducible:
  the current test explicitly includes all three validation-audit column upgrades.
- Production `RateLimitMiddleware` creates its own `InMemoryRateLimiter` per
  instance and documents N-times aggregate budget across N replicas. Successful
  direct-replica burst probes cannot prove a shared principal budget.
- No test or runtime repair is justified by the checks so far; no test count has
  changed and no inventory delta is required for this report-only round.

## Checkpoint 3

- `uv run python scripts/check-suite-inventory.py`: all 17 suites match;
  31,128 unique test identities, no duplicate evidence.
- `uv run python scripts/check-backlog-consistency.py`: passed, 168 items.
- `uv run pytest packages/maistro-server/tests/api/test_rate_limit.py -x -q`:
  26 passed.
- Executed the current `failed_promotion_checks` against committed
  `evidence/m3a-round43-shakedown.json`: precisely `sustain_duration` and
  `exact_rc_artifact` fail. Observed 420.09 seconds, required 14,400 seconds.
- The already-run soak suite includes a reachable production-middleware
  counterexample: the same authenticated principal (and, separately, the same
  pre-auth IP) receives `[200, 200, 429]` independently on both instances.
  This demonstrates local enforcement, not a replica-independent budget.

## Architecture reconciliation

Read repository instructions and ADR-081, ADR-085, ADR-081426-1f7c,
ADR-082426-82c7 and ADR-082426-e3ff. ADR-081 is **Proposed**, not an accepted
waiver of the issue's deployment requirements. Accepted ADR-085 requires
principal-keyed limiting but does not establish cluster-wide HTTP storage.
The execution and occurrence/fencing ADRs distinguish physical Attempt work
from admission identity. Consequently one Run per occurrence, terminal Run
counts and replica rejoin cannot be promoted into proof of no duplicated
physical work. No competing execution or authorization path was introduced.

UNRESOLVED: the literal replica-selection acceptance requires a shared-budget
proof which current production behavior cannot supply. An owner must settle the
release contract and, if required, authorize a focused shared-limiter change;
this lane does not silently waive acceptance or invent a second security path.

## Acceptance review (all ten issue criteria)

Historical observations below were inspected, not re-executed as live soak
traffic in this round. Unit/regression tests are not substituted for an RC soak.

| Criterion | Executed/inspected evidence and remaining gap |
| --- | --- |
| Representative RC profile | `m3a-load-profile.md` defines traffic and thresholds, but explicitly lacks concurrent users/Workspaces, Graph fan-out, successful tools/models, Canvas/Design and sustained Goal/background work. Representative RC coverage **UNVERIFIED**. |
| At least two application replicas | Round-43 evidence names both direct origins, separate resource series and replica-2 restart/rejoin. Historical preflight only; selected production RC topology **UNVERIFIED**. |
| Sustained load exposing contention/leaks/reclaim | Current evaluator rejects round 43's 420.09 seconds versus 14,400 required. Long-window pool saturation, lease reclaim, retry/backoff and leak behavior **UNVERIFIED**. |
| No duplicate physical work | Round 43 records 12 task receipts / one Run and one scheduled occurrence / one Run; its scheduled probe Run is cancelled without execution. Admission tests exercise missing/duplicate identities. Attempt physical-work fencing and Goal reconciliation under sustained load **UNVERIFIED**. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | 26 server limiter tests pass; soak tests execute production middleware and show separate replica allowances. Six historical burst paths enforce locally, not globally. Literal replica-independent allowance claim is falsified; full concurrent security/degraded acceptance **UNVERIFIED**. |
| Required metrics and explicit thresholds | Profile and round-43 pack contain threshold/latency/resource records; real uv-child sampler regression passes. Driver loop lag is not application loop lag; full worker/lease/query-contention metrics at promotion duration **UNVERIFIED**. |
| Kill/restart during active work with drain/fencing/recovery | Round 43 records SIGTERM, one-second drain, zero drain errors, no escalation and rejoin. Boot-cleanup tests pass. Physical Attempt recovery/no-duplication under RC load **UNVERIFIED**. |
| Long-running exact RC artifact/configuration | Current artifact check returns `ok=false` for host-uvicorn preflight; tested CLI refuses even synthetic four-hour preflight evidence. Round 43 is not the exact artifact. **UNVERIFIED / blocked**. |
| Findings filed/reclassified before promotion | Human evidence pack records numbered findings and invariant mappings, but this round has not established external filing/reclassification completeness. **UNVERIFIED**; GitHub mutations prohibited. |
| Publish machine/human evidence with exact hashes | Existing JSON and Markdown packs exist; round 43 records commit/config/Postgres hashes, but `git_clean=false`, prior head `3da4e035...`, no promoted application-image identity. Exact RC publication **UNVERIFIED**. |

## Disposition and handoff

**BLOCKED**, not merge-ready. The previous NEEDS-DEEP-REVIEW is not resolved by
passing deterministic gates: its acceptance gaps remain demonstrable. No fresh
host shakedown was started because even four hours of that runner cannot meet
the exact-artifact criterion. This conclusion does not depend on an assumed
lane timeout or unavailable Docker.

Next: release owner supplies immutable RC image/configuration and supported
workload scope; resolve the replica-budget contract; run the representative
production-path soak for at least four hours, instrument physical Attempt work
and recovery, then classify/file findings through an authorized actor. Do not
rerun this unchanged preflight expecting promotion approval.

Only this report changed. No production, test, gate, grant or ledger files were
edited, and no inventory change is needed. All commands above ran locally in
the assigned worktree with long validation timeouts. No GitHub mutation occurred.
Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "RC prerequisites and promotion evidence"}`.

