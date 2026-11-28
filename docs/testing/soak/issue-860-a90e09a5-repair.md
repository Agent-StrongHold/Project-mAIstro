# Issue #860 — repair round a90e09a5

## Frozen scope

- Only issue #860; assigned worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD `60730e3556a0e9698795a6f4e64d474d0eb98c7e`; supplied base `d7fb3baa6837a1a6ccb9aa5c2a1288cef6eb7743` resolves locally.
- Initial worktree clean; no incoming edits to salvage.
- Candidate edits limited to this report and `quality/vulture-baseline.json` if the explicitly requested scanner repair proves necessary. Production fixes/tests require concrete evidence before scope expansion.
- Read-only evidence: supplied dispatch snapshot and prior result/check log, repository instructions, relevant ADRs, existing soak profile/runner/tests/evidence, vulture gate and CI invocation.
- No GitHub refresh/mutation, no develop sync absent an actual conflict.

## Initial observations

No `check-*.log` files were supplied in this job directory at entry. The prior check and result paths will be inspected instead. The issue requires an exact-artifact long-running multi-replica soak; static checks alone cannot satisfy that acceptance condition.

## Validation

- Exact requested vulture scan: PASS, 1,326 reviewed identities and findings, zero unclassified/never-allowlist entries (checker base `34795962548a`). No ledger amendment warranted.
- Historical supplied `check-3.log` fails the learnings schema fence with 24 versus 21 statements. Fresh `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`: **37 passed, 6 skipped**. Failure not reproduced; skips are not live database evidence.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3,170 files.
- Commands executed with 1,200-second timeout. No guessed scanner or schema fix applied.

## Acceptance review

- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q`: **100 passed**.
- `uv run python scripts/check-suite-inventory.py`: PASS, 17 suites / 29,499 unique identities; no duplicate evidence.
- `uv run python scripts/check-merge-markers.py`: PASS.
- Fresh `uv run python -` imported the current driver and evaluated historical `evidence/m3a-round30-shakedown.json`: duration **420.08 seconds**, minimum **14,400**, failed checks **sustain_duration**, **exact_rc_artifact**. Asserted both failures and the current preflight artifact rejection. This is not a new soak.

Read repository `AGENTS.md`, documentation authority map, accepted ADRs 081426-1f7c (Attempt runtime identity), 081626-f383 (canonical execution fencing), 082526-b36a (renewal/reclaim), and 073126-c4e1 (immutable release provenance). The later reclaim contract extends the earlier fencing ADR's deferred takeover scope; that earlier deferral cannot waive recovery acceptance. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`; no competing authority introduced.

The production schema fence at `packages/maistro-core/src/maistro/persistence/pg_learnings.py:216` covers all upgrades. Its test now explicitly lists the three additional Gauntlet columns at `packages/maistro-core/tests/persistence/test_pg_learnings.py:175-177`. The historical failure is already addressed; no new test or inventory delta is warranted.

The exercised test at `tests/test_soak_promotion_gates.py:439` uses actual production rate-limit middleware and observes separate `[200, 200, 429]` allowances for the same identity on two instances. The documented process-local contract at `packages/maistro-server/src/maistro_server/api/rate_limit.py:32` is not a shared principal budget. Local enforcement passes, but the stronger issue non-bypass claim is not thereby proven.

Prior result was BLOCKED, not a CI failure requiring a speculative patch. The captured linked PR bodies and latest four primary issue comments supply no selected immutable RC artifact/configuration and retain the blocker; they are evidence, not authorization.

## Acceptance disposition

| Criterion | Executed evidence / remaining gap |
| --- | --- |
| Representative RC load profile | **UNVERIFIED complete.** `m3a-load-profile.md:153-172` explicitly lacks multiple users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and Goal/background-worker workloads. Exclusions require the selected deployment contract. |
| At least two application replicas | **UNVERIFIED for RC.** Two ASGI middleware instances tested, not two deployed RC replicas. |
| Sustained saturation, queue growth, expiry/reclaim, retry/backoff, leaks and shutdown | **UNVERIFIED.** Fresh evaluation rejects the historical short window; no new sustained production run. |
| Schedule/task/Run/Attempt physical-work uniqueness and Goal reconciliation | **UNVERIFIED.** Admission/probe regressions do not establish physical Attempt work uniqueness under sustained failover. |
| Rate/security/degraded behavior without replica-selection bypass | **UNVERIFIED as stated.** Real middleware enforces local limits but permits a fresh allowance on another replica; 100 passing focused tests cannot establish a shared budget. |
| Full telemetry and thresholds | **UNVERIFIED complete.** Profile has thresholds but no current-candidate production measurements; driver loop latency is not application event-loop latency. |
| Kill/restart during active work with drain/fencing/recovery | **UNVERIFIED.** Boot and promotion-check regressions are not active-work takeover or stale-effect rejection observations. |
| Long soak of exact promoted RC/config | **BLOCKED / UNVERIFIED.** Current `scripts/soak/run_soak.py:730-741` rejects host preflight; historical evidence fails both duration and artifact checks. No immutable RC/config selected by this assignment. |
| Findings filed/reclassified before promotion | **UNVERIFIED completeness.** Existing findings retained; no new load campaign or GitHub mutations. |
| Hash-bound machine/human evidence | **UNVERIFIED for candidate.** Historical artifacts preserved, not recertified for this HEAD; this report only records local validation. |

## Handoff

Only this report changed in this round. No code, tests, inventory counts, quality ledgers or grants changed. No production workload, remote operation or GitHub mutation was performed. Existing branch-wide changes remain intact and are not certified by this narrow check.

**BLOCKED:** the next action is selection of the immutable RC/configuration and execution of a representative production-topology campaign (at least four hours), including complete application/DB/worker telemetry, active-work fault injection and canonical Attempt recovery/fencing observations. Resolve the shared-versus-per-replica budget acceptance semantics through the existing security seam. A longer host preflight, another already-green vulture scan, or a documentation-only commit cannot fulfill those prerequisites.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "selected RC and production acceptance execution"}`. This is a local checkpoint, never integration or release approval.
