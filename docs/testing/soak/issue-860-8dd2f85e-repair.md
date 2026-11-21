# Issue #860 — repair checkpoint (job 8dd2f85e)

## Frozen scope and initial results

- Sole item: issue #860, assigned worktree `/home/dev/Git/wt/auto-860`.
- Starting HEAD verified: `6fa6bafb95f83603304fda3ea532955bfe26075c`.
- Assigned base verified: `cf4a562b65e0f459eec8e77e8b10ca7aa4f847d0`.
- Initial worktree clean; no incoming changes to salvage.
- Repair candidates frozen: this checkpoint, `docs/testing/soak/m3a-load-profile.md`,
  `docs/testing/soak/m3a-soak-evidence.md`, `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, a corresponding inventory note if tests
  change, and `quality/vulture-baseline.json` only for actual retained unbanked
  identities. Production dependencies and adjacent tests are inspection-only.
- Job directory contains no `check-*.log` files at initial snapshot. Driver
  verification is unavailable; run local checks instead. Do not assume old results.
- Prior result read: job `404870caca1845b3ab69d22a5c94b5a1` reported BLOCKED.
- Exact requested vulture command executed successfully (600-second timeout):
  `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`.
  It reports 1355 reviewed identities / 1355 findings, zero unclassified and
  zero never-allowlist. No evidence warrants a ledger amendment or dead-code fix.
- No develop-sync conflict exists. No remote operations are necessary.

## Assumption and limits

This is a writer repair, not a verifier-only round. Missing approved immutable RC
artifact/configuration cannot be replaced by the host-process preflight harness.
Do not fabricate a successful soak or introduce a competing runtime/limiter to
meet the issue. Final acceptance remains blocked unless real RC evidence exists.

## Inspection checkpoint

Read repository `AGENTS.md`, the load profile, human evidence, promotion-gate
regressions, production limiter, production Compose, and harness admission,
artifact, and load paths. Read accepted ADR-085, ADR-081626-f383,
ADR-082526-b36a, ADR-082126-f69c, and ADR-082426-82c7.

- The prior H3 documentation contradiction is already repaired at this HEAD:
  `m3a-soak-evidence.md` explicitly calls run 6 partial and acknowledges the
  replica-selection allowance. No further wording-only repair is justified.
- `RateLimitMiddleware` still instantiates an independent `InMemoryRateLimiter`
  per application process. Existing tests exercise the actual middleware with
  the same credential/client on two instances, not just mocked verdicts.
- ADR reconciliation: per-principal identity (ADR-085) does not establish a
  cluster-wide allowance. Canonical occurrence admission and durable lease
  fencing/reclamation (the scheduling and lease ADRs) do not by themselves prove
  physical-work uniqueness during a live replica failure. Do not invent another
  scheduler, authority, or rate-limit store to fill missing release evidence.
- Production Compose requires a reachable model gateway and builds application
  images; its PostgreSQL images are pg17. Historical preflight used host
  processes and pg18 without a provider. These are not equivalent artifacts.
- The runner explicitly returns `exact_rc_artifact.ok=false`. The profile
  already identifies absent users/Workspaces, graph fan-out, successful
  tool/model calls, Design/Canvas, Goal reconciliation, application-loop metrics,
  detached-worker measurements and physical recovery proof.
- Existing tests provide meaningful failure cases for admission without an
  observed identity, incomplete rate-probe topology, a disabled replica limiter,
  missing artifact gates and missing process measurements. No new test is
  needed for this documentation-only checkpoint; inventory delta is zero.

ADR-081 was also inspected: it is **Proposed**, not accepted authority. The
shipped production Compose reference supplies the two-replica deployment claim;
this checkpoint does not elevate proposed deployment guarantees into proof.

## Executed validation

All test/gate commands used a 600-second timeout. Results are from this round,
not copied from the prior worker:

| Command | Outcome |
| --- | --- |
| Exact vulture command above | PASS; 1355/1355, no ledger change justified |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS; 2836 files already formatted |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py -x -q -rs` | 80 passed, 5 skipped |
| `uv run pytest tests/test_prod_stack_boot_contract.py -x -q` | 8 passed |
| `uv run python scripts/check-suite-inventory.py` | PASS; all 14 suites match |
| `uv run python scripts/check-merge-markers.py` | PASS |
| `uv run python scripts/check-deployment-claims.py` | PASS |
| `uv run python scripts/check-compose-secrets.py` | PASS; 8 Compose files |
| `git diff --check` | PASS |

The five skips require `MAISTRO_TEST_PG_DSN` pointing at a migrated database.
They are not database-concurrency evidence. No database, model gateway,
production replicas, or long-running soak was launched by this round.

An executed `uv run python` evaluator imported the current
`failed_promotion_checks` and loaded these four explicit historical packs:

| Evidence JSON under `docs/testing/soak/evidence/` | Observed duration | Current result |
| --- | --- | --- |
| `m3a-soak-evidence.json` | top-level duration absent | Rejected, including artifact and duration |
| `m3a-repair-validation.json` | top-level duration absent | Rejected, including artifact and duration |
| `m3a-round5-final.json` | 90.17 seconds | Rejected: rate, duration, artifact |
| `m3a-round6-shakedown.json` | 90.43 seconds | Rejected: duration, artifact |

The command asserted that **every** pack fails both `exact_rc_artifact` and
`sustain_duration`; all assertions passed. These are historical evidence
re-evaluations, not new soak executions. The middleware regressions executed
both authenticated and unauthenticated identity cases: replica 1 responds
`200,200,429`; replica 2 then independently responds `200,200,429`, while
replica 1 remains exhausted. Thus local limiter tests passing actually
falsifies a shared-budget inference rather than satisfying non-bypass.

## Acceptance accounting (all ten criteria)

| Criterion | Evidence and disposition |
| --- | --- |
| Representative RC load profile | PARTIAL: profile exists; `m3a-load-profile.md:152` explicitly lists missing users/Workspaces, fan-out, successful calls, Design/Canvas and Goal/worker coverage. Applicability to the selected RC is UNVERIFIED. |
| At least two supported application replicas | Compose declares two; 8 boot-contract tests pass, but deployed RC behavior is UNVERIFIED. ASGI limiter instances are not a deployment. |
| Sustained saturation, queue growth, lease reclaim, retry/backoff, leaks and shutdown | UNVERIFIED: latest frozen pack records 90.43 seconds, not 14400. No live load was executed here. |
| No duplicate physical schedule/task/Run/Attempt/Goal work | UNVERIFIED: admission tests and one historical occurrence do not prove physical execution/reconciliation across replicas. Accepted lease and recurrence ADRs retain the canonical spine. |
| Rate/security/degraded concurrency non-bypass | UNMET for an aggregate principal allowance: actual middleware tests reproduce independent replica budgets (`rate_limit.py:25`, test at `test_soak_promotion_gates.py:439`). Full RC security/degraded behavior is UNVERIFIED. |
| All requested metrics with explicit thresholds | PARTIAL: process-group sampler tests pass; application-loop latency, detached workers and complete production metric/threshold coverage remain UNVERIFIED. Driver-loop lag is not an application measurement. |
| Kill/restart active work with drain/fencing/recovery | UNVERIFIED: historical process rejoin and terminal counts do not correlate physical Attempt effects; no active RC failure injection ran here. |
| Long-running exact RC artifact/configuration soak | UNMET: `run_soak.py:635` deliberately cannot certify the Compose artifact; all four historical packs fail current artifact and duration gates. No selected immutable RC manifest was supplied. |
| Findings filed/reclassified before promotion | PARTIAL: local F-series findings and earliest-invariant classifications exist in the evidence document. External filing is UNVERIFIED; GitHub mutations are forbidden in this lane. |
| Human/machine evidence bound to exact image/package/commit/config | PARTIAL: historical packs exist, but qualifying RC evidence is UNVERIFIED; this checkpoint is not soak evidence. |

## Handoff

**BLOCKED.** No runtime/configuration, test, ledger, or historical evidence file
was changed. The only changed file is this checkpoint. The explicit CI-repair
request has no remaining scanner failure at the assigned starting HEAD; banking
unchanged identities or changing retained code would be a guessed repair.

Next: release owner must select and supply the immutable RC image/configuration
and provision its actual model/services; resolve the aggregate-rate-limit
acceptance mismatch through the canonical policy/implementation owners; complete
the representative workloads and production-side measurements; then execute at
least 14400 seconds with correlated physical-work failure/recovery evidence.
Any subsequent code/runtime-config change requires a fresh soak. A longer run of
the existing host emulator is not a substitute. Do not repeatedly rerun this
CI-only lane expecting a missing RC soak to appear.

Progress: checked 1 assigned item; done 0 acceptance-complete items; skipped 0
items; command errors 0; blocked 1. Validation checkpoint is committed locally;
no push, remote mutation, branch deletion, or integration approval is requested.
