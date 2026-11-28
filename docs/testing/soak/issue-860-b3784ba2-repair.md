# Issue #860 — b3784ba2 repair checkpoint

## Frozen scope

- One assigned item: issue #860, branch `auto-860`, starting HEAD
  `22eb1077fc9fbaa682275242277a8b52408ad925`, base
  `33bcd3ce28830032403e23ce82de8ccfaca2acce`.
- Worktree was clean. No incoming changes to salvage.
- Inspect existing soak profile/evidence, harness, promotion tests, production
  rate-limit/deployment contracts, relevant ADRs, and the explicitly requested
  vulture gate. Change only evidence-backed defects and this report; amend the
  vulture ledger only if the requested gate identifies reviewed retained debt.
- Snapshot: no `check-*.log` files exist in the supplied job directory at start.
  Prior reports are context, not executed acceptance evidence.
- Assumption: this is the writer/CI-repair lane; do not fabricate a long-running
  RC soak or treat a preflight as production acceptance. No GitHub mutations.

## Progress

Initial repository instructions read; expected HEAD and clean worktree confirmed.
Requested Vulture gate executed (exit 0): 1371 findings / 1371 reviewed
identities; unclassified=0, never_allowlist=0; trusted base `4df9dd9bde4c`,
candidate `22eb1077fc9f`. No unbanked identities or justified ledger edit.
Prior result and current profile/evidence read: the shared-limiter claim is
already corrected; exact-RC and representative-profile gaps remain explicit.
Read ADR-085 (Accepted), ADR-081 (Proposed), ADR-081626-f383 (Accepted), and
ADR-083126-5e62 (Accepted). Reconciliation: durable Attempt fencing is distinct
from occurrence admission and does not alone establish lease-expiry recovery.
No competing scheduler/authorization or acceptance waiver will be introduced.

## Executed validation

- `uv run ruff check .` — exit 0, all checks passed.
- `uv run ruff format --check .` — exit 0, 2720 files already formatted.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs`
  — exit 0, **88 passed, 5 skipped**, 7.67 s. The five PG integration tests
  require a migrated `MAISTRO_TEST_PG_DSN` not configured for this invocation.
  Tests exercise real production limiter instances (both identity classes),
  a real uv child for RSS/descriptor sampling, canonical admission backpressure,
  and fail-closed artifact gates. Mock probe responses and static Compose tests
  are not live production soak evidence.
- Inspected `deploy/docker-compose.prod.yml`: two server services are declared,
  images are not immutable RC selections, and an external model gateway/key is
  required. The existing harness instead boots host processes.

- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests --suite packages/maistro-server/tests --suite tests/`
  — exit 0: counts match (11958 / 485 / 4320).
- `uv run python scripts/check-security-inventory.py` — exit 0: 59 cited paths,
  23 inventory rows, 2 counted claims match (not blanket prose verification).
- `DOCKER_HOST=unix:///var/run/docker.sock docker info --format '{{.ServerVersion}}'`
  — exit 0, Docker 29.7.2 available. Docker unavailability is not the blocker.
- An executed `uv run python` probe imported the current `run_soak.py` and ran
  `failed_promotion_checks` on the frozen four historical JSON packs. Assertions
  that each fails both `sustain_duration` and `exact_rc_artifact` passed (exit 0):
  - `m3a-soak-evidence.json`: also rate, failover, nonterminal, availability,
    and drain failures; no top-level duration.
  - `m3a-repair-validation.json`: also task admission, failover, nonterminal,
    availability, and drain failures; no top-level duration.
  - `m3a-round5-final.json`: 90.17 s; also rate failure.
  - `m3a-round6-shakedown.json`: 90.43 s; duration and artifact failures.
  Successful assertions mean these packs were rejected, not that they passed.
- Production reachability verified: `maistro_server/main.py:588` installs the
  same `RateLimitMiddleware` exercised by the replica-selection regression.
  `rate_limit.py:25-30` explicitly documents process-local N-times allowance.

## Acceptance audit

| Supplied criterion | Current evidence / disposition |
|---|---|
| Representative concurrent users/Workspaces and request/execution mix | PARTIAL. Profile inspected; one API key and absent successful model/tool, fan-out, Canvas/Design and Goal/background traffic are acknowledged. Representative RC coverage UNVERIFIED. |
| At least two application replicas | PARTIAL. Compose declares two and boot-contract tests pass. Historical host-process preflight is not the production artifact. Exact-RC multi-replica execution UNVERIFIED. |
| Sustained saturation, queue growth, reclaim, retries, leaks, shutdown | UNVERIFIED. All four historical packs rejected by current duration/artifact gates; no new long-running soak executed. |
| Schedule/task/Run/Attempt physical uniqueness and Goal reconciliation | UNVERIFIED. Admission and backpressure regression tests pass, but schedule claim/cancel and terminal Run counts do not prove physical-work fencing, recovery or sustained Goal reconciliation. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | NOT MET. Executed `test_replica_selection_has_an_independent_production_allowance` for authenticated and unauthenticated identities: first replica returns 200,200,429; second independently returns 200,200,429 (`tests/test_soak_promotion_gates.py:482-486`). RC security/degraded behavior remains UNVERIFIED. |
| Required telemetry and explicit pass/fail thresholds | PARTIAL. Profile and live process sampler tests inspected/executed; historical wrapper-only RSS/FD measurements remain invalid. Application event-loop latency, complete worker counts and long-window saturation/leak observations UNVERIFIED. |
| Kill/restart during active work proves drain/fencing/recovery | UNVERIFIED. Historical exit/rejoin is not physical Attempt recovery proof. No new production kill/restart performed. |
| Long-running exact RC artifact/configuration soak | NOT MET. `run_soak.py:635-645` explicitly rejects the emulator artifact; round 6 records 90.43 s versus 14400 s (`m3a-round6-shakedown.json:221-224`). No selected immutable RC image/configuration was supplied, and no qualifying soak exists among the inspected packs. |
| Findings filed/reclassified at earliest invariant | PARTIAL. Existing evidence records M3-A evidence-validity classifications. External filing UNVERIFIED; GitHub mutations prohibited. No new runtime finding claimed. |
| Machine/human evidence tied to exact image/package/commit/config | PARTIAL. Historical preflight JSON/Markdown preserved with old identities. Qualifying RC evidence UNVERIFIED. |

## Handoff

**BLOCKED.** Previous block is not resolved. The requested CI gate already
passes; no evidence supports changing the per-identity ledger or deleting code.
The prior shared-store documentation defect is already corrected. This round
changes only this validation report; no code/runtime configuration, test,
inventory count, ledger or raw evidence changes. No test additions means no
inventory-delta note is required.

Unblocking requires a selected immutable RC image and full runtime/provider
configuration, resolving the cross-replica allowance mismatch, and a production
runner with the missing representative workload, telemetry and physical-work
recovery oracles. Then execute at least four hours against that exact artifact,
repeating after code/runtime-config changes. A longer run of the current
emulator cannot establish acceptance. Do not infer promotion approval from
unit tests or green static CI.

Only local commit/checkpoint performed; no push, PR, issue filing or closure.
Progress: checked=1, done=0, skipped=0, errors=0; next=RC selection and production
soak implementation/execution with the rate-limit contract resolved.
