# Issue #860 — bounded repair checkpoint (f8c5850d)

## Frozen scope

- Assigned issue: #860 only; branch `auto-860`.
- Starting HEAD: `8043f4a0069abfa6848a59ca70207fa566ea3495` (verified).
- Assigned base: `321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`.
- Worktree was clean; no incoming work to salvage.
- Process the captured issue acceptance and reported vulture failure only.
- Read scope: repository instructions, relevant execution/deployment ADRs,
  existing soak harness/profile/tests, CI gate configuration, supplied job evidence.
- Write scope: this checkpoint; production code/tests/ledger only if fresh
  evidence establishes a focused repair (no speculative ledger edits).

## Initial evidence and ambiguity

The supplied previous result is BLOCKED, with all production-soak acceptance
unverified. This is a claim to recheck, not acceptance evidence. The current job
directory contains no driver `check-*.log` files at initial inspection. Inspect
the explicitly cited prior `check-3.log` and execute fresh validation instead.
No release-candidate artifact/configuration or deployment target is identified
in the issue acceptance text. Do not substitute a synthetic local run for it.

## Fresh validation checkpoint

Commands executed with a 1200-second timeout, all exit 0. Logs are in the
assigned job directory (not production soak evidence):

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  — 1322 reviewed identities / 1322 findings, zero unclassified and
  never-allowlist findings (`worker-vulture.log`). No ledger repair justified.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q`
  — 136 passed, 6 skipped (`worker-tests.log`).
- `uv run ruff check .` — passed (`worker-ruff.log`).
- `uv run ruff format --check .` — 3301 files already formatted
  (`worker-format.log`).

The historical check-3 failure is a 24-versus-21 schema-statement expectation,
not a vulture failure. Its current suite passes; skips are not live database
validation. No source/test/ledger change is warranted by these fresh results.

Read accepted ADR-081426-1f7c, ADR-081626-f383 and ADR-082526-b36a. The later
reclaim/heartbeat contract extends the older fencing boundary; preserve
Goal -> Graph -> Run -> NodeRun -> Attempt and use existing canonical seams.
ADR-081 is Proposed, not an accepted override of these execution contracts.

Additional gates (1200-second timeout, exit 0):

- `uv run python scripts/check-ratchet-provenance.py` — 53 quality JSON
  consumers have explicit provenance (`worker-provenance.log`).
- `uv run python scripts/check-shipped-surface-truth.py` — complete matrix
  (`worker-shipped-surface.log`).
- `git diff --check` — passed.

## Reachable production behavior

`packages/maistro-server/src/maistro_server/main.py:648` installs
`RateLimitMiddleware`; `api/rate_limit.py:93` constructs an in-memory limiter.
The executed test at `tests/test_soak_promotion_gates.py:439` observes
`[200, 200, 429]` independently on both instances for the same identity,
authenticated and unauthenticated. Local 429 enforcement does not establish
replica-selection-resistant aggregate enforcement. This does not by itself
prove the deployed ingress policy fails: that policy still needs testing.
The production-router regression at line 569 also records a peer receipt 404.
Neither ASGI test is a deployed two-replica soak.

`scripts/soak/run_soak.py:744` explicitly rejects exact-RC equivalence for its
host-process preflight. Executed promotion-gate regressions preserve that
failure even for simulated long-duration evidence. The production reference
Compose file builds from source and asks operators to pin digests; it is not
an immutable selected RC. The captured linked PR bodies/recent issue comments
do not supply a new exact-RC target that resolves the previous blocker.

## Acceptance: all ten criteria

| Criterion | Fresh evidence and remaining boundary |
| --- | --- |
| Representative RC profile | UNVERIFIED. `docs/testing/soak/m3a-load-profile.md:165` explicitly lists missing users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and Goal/background reconciliation. RC applicability must be selected, not assumed. |
| Two deployed application replicas | UNVERIFIED. Compose declares two; executed tests use ASGI instances, not the deployed topology. |
| Sustained saturation, queue growth, reclaim, retries, memory/FD/process leaks | UNVERIFIED. Short regression tests do not observe the required long window. |
| No duplicated physical schedule/task/Run/Attempt/Goal work | UNVERIFIED. Admission/receipt tests are not physical-work correlation under load. |
| Replica-selection-resistant rate/security/degraded behavior | UNVERIFIED for the deployment. Independent local allowances reproduced through the production middleware. |
| All required telemetry and thresholds | UNVERIFIED. No fresh production PostgreSQL contention, application-loop lag, worker, RSS/FD, queue, error/timeout series. |
| Active-work replica kill/restart with drain/fencing/recovery | UNVERIFIED. No real active production work was killed/recovered this round. |
| Long exact-RC artifact/configuration soak | UNVERIFIED. No immutable promotion target established; the existing runner is deliberately preflight-only. |
| Findings classified to earliest broken invariant | UNVERIFIED for completeness. Existing local rate/receipt prerequisites remain documented; no GitHub mutations performed. |
| Machine/human evidence bound to image/package/commit/config hashes | UNVERIFIED for production. These source-bound validation logs are not an exact-RC soak bundle. |

## Disposition and next input

**BLOCKED.** The reported historical schema failure does not reproduce and the
exact-debt gate is clean. No speculative scanner, ledger, runtime, or test
repair was made. This report is the only changed file; no test additions means
no inventory delta. Existing tests provide meaningful focused validation, not
acceptance closure.

Required next: identify the immutable RC artifact and normalized deployment
configuration, resolve representative workload applicability and replica-local
enforcement/receipt prerequisites through existing owners, then execute the
long production soak with physical-work correlation, recovery and complete
telemetry. Re-running this unchanged repair assignment cannot supply those
inputs. Preserve the fail-closed promotion gate.

Checkpoint: checked 1 issue; acceptance-complete 0; skipped 0; validation
errors 0; next is the RC/deployment evidence prerequisite. Local writer handoff
only, not integration approval.
