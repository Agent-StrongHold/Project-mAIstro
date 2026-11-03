# Issue #860 — repair checkpoint (job 29f1948b)

## Frozen scope

- Single item: issue #860, branch `auto-860`, starting HEAD
  `2fcf9139d7a2a54628d0a6092b755be0a9e53f8b`, assigned base
  `3c761d14db944a727fa0744444bc67cfe36d49f7` (both resolved locally).
- Clean incoming worktree; no uncommitted work to salvage.
- Evidence: supplied dispatch-context.json, prior result 27b7f154, prior
  check-3.log from 98a11313. Current job directory contained no check logs.
- Frozen repair surfaces: this report; `quality/vulture-baseline.json` only
  if the required scan finds reviewed retained debt; and
  `packages/maistro-core/tests/persistence/test_pg_learnings.py` plus an
  inventory note only if the reported schema-fence failure still reproduces.
- Read-only acceptance surfaces: `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, soak profile/evidence, relevant ADRs,
  production schema and rate-limit implementation, adjacent tests and CI gates.
- Assumption: this is a writer CI-repair round, not permission to designate an
  arbitrary checkout as the immutable release candidate. No GitHub mutations,
  new execution/authorization authority, or promotion claims.

## Initial evidence

The supplied prior check-3.log reports 24 schema DDL calls versus 21 expected
in the schema-fence test. The prior result is BLOCKED for missing exact-RC
soak evidence and independent per-replica rate allowances. Neither claim is
accepted without fresh validation. The inherited branch has a large diff;
this round will not repair unrelated inherited changes.

## Fresh initial validation

- Required exact Vulture command: PASS, 1323 reviewed identities / 1323
  findings; zero unclassified and never-allowlist findings. Checker-selected
  base `4aa68edc0b6b`. No unbanked identity exists to justify a ledger edit.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  37 passed, 6 skipped (1.55 seconds). The old failure does not reproduce:
  the expected DDL list now includes the three audit columns at lines 175–177.
- The current load profile explicitly identifies the runner as host-process
  preflight, not production Compose, and records missing representative
  workloads. No speculative code repair.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS (3270 files).
- `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs`:
  74 passed (2.39 seconds). Combined with the schema suite: 111 passed,
  6 skipped. No live database or deployed soak is implied by this result.
- `uv run python scripts/check-suite-inventory.py`: PASS, 17 suites,
  31128 unique identities, no duplicate evidence.
- `uv run python scripts/check-deployment-claims.py`: PASS (component-existence
  check, not runtime deployment validation).

Commands used 1200-second timeouts. The supplied issue body was read from the
frozen dispatch snapshot. The current workflow invokes the same Vulture,
inventory and deployment-claims scripts. No test addition or inventory delta.

## Architecture reconciliation

Read accepted ADR-085, ADR-081626-f383 and ADR-082526-b36a. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`; reclaim/heartbeat extends the
older fencing ADR's deferred recovery boundary, not a waiver of recovery
validation. ADR-085 requires principal-based rate identity, but that does not
prove a shared cluster budget. Production middleware documents N-times-limit
semantics and constructs an independent in-memory limiter per instance.
The executed `test_replica_selection_has_an_independent_production_allowance`
checks the same authenticated and pre-auth identities on two instances and
observes `[200, 200, 429]` on each. Issue #860's stronger non-bypass requirement
is not proven by local enforcement; reconciliation remains UNRESOLVED rather
than silently changing the existing authorization path.

## Acceptance disposition

| Criterion | Executed evidence / remaining gap |
| --- | --- |
| Representative RC profile | **UNVERIFIED**. `m3a-load-profile.md:152` explicitly lacks concurrent users/Workspaces, Graph fan-out, successful tool/model calls and Design/Canvas/Goal/background workloads. No RC applicability decision supplied. |
| Two deployed application replicas | **UNVERIFIED**. Boot-contract tests pass; two ASGI limiter instances are not deployed replicas of an exact RC. |
| Sustained saturation, queues, reclaim, retries, leaks | **UNVERIFIED**. Sampler and admission tests pass, but no sustained production load was executed this round. |
| No duplicate physical work | **UNVERIFIED**. `run_soak.py:1044` cancels the schedule admission probe without executing work; its admission counts do not prove Attempt fencing or Goal reconciliation. |
| Rate/security/degraded non-bypass | **UNVERIFIED** at deployment grade; independent replica allowances reproduced in `tests/test_soak_promotion_gates.py:439`. The production app installs this middleware at `main.py:648`, with instance-local state at `api/rate_limit.py:93`. |
| Complete telemetry and thresholds | **UNVERIFIED**. Thresholds are documented, but `run_soak.py:1410` samples driver-loop lag, not application-loop latency. No fresh RC telemetry series. |
| Active-work restart/drain/fencing/recovery | **UNVERIFIED**. Passing cleanup and evidence-gate tests do not perform deployed active-work recovery. |
| Long exact-RC soak | **UNVERIFIED / BLOCKED**. `run_soak.py:730` unconditionally rejects host-preflight artifact certification. Executed four-hour CLI tests use synthetic evidence, not four hours of traffic. `deploy/docker-compose.prod.yml:11` requires image pinning; no immutable RC/config designation supplied. |
| Findings disposition before promotion | Local blockers recorded here; external filing/reclassification **UNVERIFIED**. No GitHub mutations performed. |
| Hash-bound machine/human RC evidence | **UNVERIFIED**. This source-validation report is not deployed soak evidence; historical artifacts were not rewritten or certified for this HEAD. |

## Handoff

**BLOCKED**. The reported deterministic failure is no longer reproducible and
the requested exact-debt gate passes. No source, tests, runtime configuration,
ledger, grant or historical raw-evidence changes are justified by these results.
Only this report changes; no inventory note is needed because no tests change.
No sync conflict exists. Docker availability is not asserted as a blocker;
a deployment was not attempted without the missing RC designation and workload
contract. Repository instructions and documentation authority map were read.

Next: designate immutable RC/configuration, reconcile replica-rate expectations,
complete the representative production workload and physical-effect/telemetry
oracles, then execute the required >=14400-second unchanged-artifact soak with
active-work recovery. Re-dispatching the already-fixed schema assertion or
requesting speculative Vulture ledger edits cannot resolve these prerequisites.

Progress: checked 1 issue; done 0 acceptance-complete issues; skipped 0 issues;
errors 0 validation commands; 6 tests skipped. This local report commit completes
the bounded repair investigation, not issue #860 or integration approval.


