# Issue #860 repair — c994a752

## Frozen scope

- One issue: #860; branch `auto-860`; starting HEAD
  `cda3f0f79fbecdaa3fdee9ef759a61f7834e24c4`; supplied base
  `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Starting worktree clean. No salvage patch required.
- Repair targets: `packages/maistro-core/tests/persistence/test_pg_learnings.py`,
  its production counterpart `packages/maistro-core/src/maistro/persistence/pg_learnings.py`
  only if evidence warrants, `quality/vulture-baseline.json` only for observed
  reviewed identities, and this report plus an inventory note if tests change.
- Read-only acceptance targets: `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, `docs/testing/soak/m3a-load-profile.md`,
  `docs/testing/soak/evidence/m3a-round43-shakedown.json`, relevant ADRs and CI gates.
- No GitHub mutations, develop merge, or new execution/authorization authority.

## Initial evidence and assumptions

The supplied prior `check-3.log` reports 24 production schema statements versus
21 expected by the fence test. Reproduce before changing anything.
The current job directory contains no driver `check-*.log` files at initial
inspection. The prior result reports BLOCKED on exact-RC soak acceptance;
this is a claim to recheck, not acceptance proof. Assignment is writer repair,
not read-only verification. No exact RC deployment identity was supplied.

## Results

- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  **37 passed, 6 skipped** (PostgreSQL integration tests not configured).
  The supplied failure is stale: the current independent expected-DDL list
  already includes all three Gauntlet audit columns. No test weakening needed.
- Requested exact Vulture command: **PASS**, 1323 reviewed identities / 1323
  findings, zero unclassified and zero never-allowlist. No unbanked identities;
  therefore no justified ledger amendment.
- Issue acceptance body extracted from the frozen dispatch snapshot. Its ten
  criteria require deployment/load evidence, not merely green unit tests.
- `uv run ruff check .`: **PASS**.
- `uv run ruff format --check .`: **PASS**, 3270 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py -x -q`: **65 passed**.
  This includes production RateLimitMiddleware instances demonstrating that
  replica selection grants a second allowance to the same credential/IP;
  passing that regression test falsifies acceptance, it does not prove safety.

## Architecture reconciliation

Read repository `AGENTS.md`, documentation authority map, ADR-081 (Proposed),
ADR-085 (Accepted), ADR-081626-f383 (Accepted), and ADR-082126-f69c (Accepted).
Recurrence produces canonical Runs, and physical Attempt writes require the
canonical store's fence. Admission deduplication alone cannot establish absence
of duplicate physical effects. No second scheduler, Goal store or authorization
path is warranted. ADR-085's per-principal limit is not evidence of a shared
multi-replica allowance. Proposed deployment ADR-081 cannot waive the issue's
exact-RC requirement. Existing preflight limitations remain blockers.

## Acceptance audit

These results distinguish inspected production behavior and executed local tests
from deployment evidence. No new load run is claimed.

| Issue criterion | Executed evidence / remaining gap |
| --- | --- |
| Representative RC load profile | **UNVERIFIED**. `main_async` uses one credential and five request classes (`scripts/soak/run_soak.py:1373`); no concurrent Workspace population, Graph fan-out, successful provider/tool, Canvas or sustained background workload. The profile explicitly lists these gaps. |
| At least two deployed application replicas | **UNVERIFIED** for the selected RC. Two ASGI middleware instances in the executed tests are not two deployed application replicas. The harness boots host processes, not the promoted image. |
| Sustained saturation, reclaim, retries and leak observations | **UNVERIFIED**. Executed current evaluator on retained `m3a-round43-shakedown.json`: duration **420.09 seconds**, failures `sustain_duration` and `exact_rc_artifact`. No new long-window observation. |
| No duplicated physical work / Goal reconciliation | **UNVERIFIED**. `scripts/soak/run_soak.py:1044` cancels the schedule probe's queued Run without execution. Admission identity regression tests do not establish physical-work uniqueness or Goal reconciliation. |
| Security/degraded behavior cannot be bypassed by replica selection | **Contrary evidence reproduced**. `tests/test_soak_promotion_gates.py:439` runs real production middleware with the same credential/IP: each replica returns `[200, 200, 429]` independently. `rate_limit.py:93` constructs a per-instance in-memory limiter. Local enforcement is not cluster-wide enforcement. |
| Required telemetry with explicit thresholds | **UNVERIFIED** in a complete deployed RC run. The process-group sampler test executes a real child and observes memory/descriptors; driver loop lag (`run_soak.py:1410`) is not application loop lag. This is partial instrumentation, not complete acceptance. |
| Active-work kill/restart, drain/fencing/recovery | **UNVERIFIED**. Driver counts process exit, HTTP failures and liveness rejoin (`run_soak.py:1276`, `:1427`); no physical-effect accounting around a leased Attempt was exercised this round. |
| Long exact-RC soak; invalidate after changes | **UNVERIFIED / blocked**. Direct execution of `preflight_artifact_check()` returns `ok=False`, topology `host-uvicorn-preflight`; the tested CLI rejects even a synthetic four-hour preflight. No exact immutable RC image/configuration supplied or run. |
| Disposition of load findings before promotion | **UNVERIFIED** externally. Historical snapshot and repository notes are not fresh proof of all dispositions. No GitHub mutation performed. |
| Machine/human evidence bound to exact artifact hashes | **UNVERIFIED** for promotion. Historical JSON exists but current evaluator rejects it; this report is local validation, not a new hash-bound RC evidence pack. |

## Focused repair decision and handoff

No production, test, gate or ledger edit is justified by the assigned stale
failure or the clean scanner result. No tests were added, so no inventory delta
is introduced. Only this report changes in this round; existing work is preserved.

The in-process tests and static checks cannot close #860. Next required work is
an explicitly identified RC deployment and a representative production-path
soak with physical-effect/lease/Goal reconciliation accounting and the full
telemetry contract, plus resolution of the observed replica-selection allowance
before promotion. Do not substitute another short host preflight or another
ledger amendment for that evidence.

Checkpoint: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "exact-RC evidence and replica-budget resolution"}`.
Verdict: **BLOCKED** (local validation complete; issue acceptance not established).
Final validation: `git diff --check` passed; only this report was untracked.
The report is committed locally for handoff, not integration approval.
