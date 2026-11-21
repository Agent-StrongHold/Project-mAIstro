# Issue #860 repair — job 73d2846f

## Frozen scope

- Only issue #860, branch `auto-860`, assigned worktree `/home/dev/Git/wt/auto-860`.
- Starting head: `8264bf024d699a0e02b3295b78635f689d7f094d` (resolved).
- Supplied base: `2154f845347c9541016288c760f8da3f5cd2e064` (resolved by diff).
- Initial worktree clean; no incoming uncommitted work to salvage.
- Evidence sources: supplied dispatch-context.json, prior result 1ffbf8ec,
  prior check-3.log in job 98a11313. No check-*.log exists in this job directory.
- Review scope: repository instructions, relevant execution/soak ADRs,
  scripts/soak/run_soak.py, tests/test_soak_promotion_gates.py, current load
  profile, exact Vulture gate and its workflow/script/ledger.
- Intended writable files: this report; quality/vulture-baseline.json only if
  the requested exact scan identifies reviewed retained debt. No guessed fixes.

## Initial result

The supplied previous result is BLOCKED, not acceptance evidence. The assigned
base-to-head diff is broad and includes unrelated historical changes; this round
will preserve it, not attempt an unassigned synchronization or cleanup.

## Fresh CI evidence

- Exact requested Vulture command passed: 1323 reviewed identities / 1323
  findings, zero unclassified, zero never-allowlist. No ledger amendment justified.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
  passed: 37 passed, 6 skipped. The supplied historical check-3.log failure
  (24 DDL statements versus 21 expected) is not reproducible at this head.
- Both commands used a 1200-second timeout. Skipped database tests do not prove
  live concurrent schema safety.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3277 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q`:
  80 passed.
- `uv run pytest packages/maistro-server/tests/api/test_rate_limit.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  27 passed.
- `uv run python scripts/check-backlog-consistency.py`: PASS, 168 items.
- `uv run python scripts/check-adr-index.py`: PASS.
- These validations also used a 1200-second timeout. No tests added or changed;
  no inventory delta is necessary. The production-middleware regression
  demonstrates independent per-replica allowances, not a shared budget.

## Architecture reconciliation

Read `AGENTS.md`, `docs/README.md`, accepted ADR-081226-a66b,
ADR-081626-f383 and ADR-085, the current load profile, soak gates, production
rate limiter, schema declarations and adjacent tests. The exact Vulture command
matches `.github/workflows/quality.yml:1078`.

Preserve Goal -> Graph -> Run -> NodeRun -> Attempt. ADR-081626-f383 explicitly
leaves lease-expiry takeover undefined; the issue's reclaim requirement is not
permission to introduce another execution authority. ADR-085 requires principal
identity for limits; per-process enforcement cannot establish the issue's
replica-selection non-bypass claim. No architecture or policy changed.

## Acceptance audit against the supplied issue body

| Criterion | Executed evidence / remaining gap |
| --- | --- |
| Representative RC workload | UNVERIFIED. `docs/testing/soak/m3a-load-profile.md:170` documents absent concurrent users/Workspaces, fan-out, successful tools/models, Design/Canvas and Goal/background workloads. No selected immutable RC/config was supplied for this round. |
| At least two deployed replicas | UNVERIFIED. Executed tests exercise ASGI instances, not a deployed RC topology. |
| Sustained saturation, queues, reclaim, retry/backoff, leaks and shutdown | UNVERIFIED. No sustained deployment run executed. Schema tests and short sampler tests cannot prove this. |
| No duplicated physical work, including schedule/task/Run/Attempt/Goal reconciliation | UNVERIFIED. `scripts/soak/run_soak.py:1067` cancels the admission probe's queued Run without execution; admission uniqueness is not physical-work uniqueness. |
| Effective rate/security/degraded behavior without replica-selection bypass | Not proven. Executed `tests/test_soak_promotion_gates.py:439` tests actual middleware with identical identity on both replicas: each accepts two requests then returns 429. Independent allowances are reproduced for authenticated and unauthenticated requests. Production creates a local limiter at `packages/maistro-server/src/maistro_server/api/rate_limit.py:93`. Full deployed security/degraded behavior remains UNVERIFIED. |
| Required telemetry and explicit pass/fail thresholds | UNVERIFIED at deployment level. Sampler tests passed; no fresh PostgreSQL/application-loop/worker/queue telemetry series captured. Driver loop latency is not application loop latency. |
| Kill/restart during active work with drain/fencing/recovery | UNVERIFIED. Boot-cleanup regression tests passed, but they do not establish active-work recovery. |
| Long soak of exact promoted artifact/config | UNVERIFIED. `scripts/soak/run_soak.py:744` unconditionally rejects its host-process preflight as exact-RC evidence. The passing four-hour regression uses synthetic duration, not four hours of traffic. |
| Findings filed/reclassified to earliest broken milestone | Backlog consistency check passed; complete load-derived classification UNVERIFIED. No live-load findings generated and no GitHub mutations performed. |
| Human/machine evidence bound to image/package/commit/config hashes | UNVERIFIED. This local validation report is not a production soak evidence pack. |

## Disposition and handoff

**BLOCKED**, not promotion-ready or integration approval. Only this report changes.
The historical schema expectation already includes the three additional columns
at `packages/maistro-core/tests/persistence/test_pg_learnings.py:177`–179.
No evidence warrants another test, source or ledger amendment. All inherited
work is preserved. No grant edits, gate weakening, network mutations or ref
synchronization were performed.

Next: provide the immutable promotion RC/config and an authorized deployment
workload covering the missing surfaces; resolve the replica-selection policy at
the existing enforcement seam and reclaim semantics under accepted authority;
then capture a >=4-hour exact-artifact soak with active-work restart and
hash-bound telemetry. Repeating the already-clean historical CI check cannot
satisfy those requirements.

Progress: checked 1; done 0 acceptance-complete; skipped 0; errors 0; blocked 1.
CI-repair investigation complete, with no reproducible CI defect. Stop rather
than inventing a scanner finding or starting another issue.
