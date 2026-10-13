# Issue #860 — repair checkpoint (67e41f99)

## Frozen scope

Only issue #860 in `/home/dev/Git/wt/auto-860`, branch `auto-860`.
Starting HEAD verified: `7d42534d2ced81078b61a111e29f2ad018d42708`;
supplied base resolves: `2154f845347c9541016288c760f8da3f5cd2e064`.
Initial worktree clean; no salvage needed. No current-job check logs supplied.

Frozen processing scope: supplied dispatch context and prior result/log;
repository instructions and relevant ADRs; `scripts/soak/run_soak.py`,
`tests/test_soak_promotion_gates.py`, `docs/testing/soak/m3a-load-profile.md`,
`docs/testing/soak/m3a-soak-evidence.md`, adjacent production rate limiter and
its tests, `scripts/check-vulture-baseline.py`, `quality/vulture-baseline.json`,
CI gate invocation, and this report. Existing broad branch history is preserved,
not a mandate to repair unrelated issues. Ledger edits only if fresh scan
identifies reviewed retained identities. No GitHub mutations.

Ambiguity: writer/repair assignment takes precedence over verifier-only wording.
Prior BLOCKED verdict is not presumed correct. Acceptance validation pending. Fresh exact CI vulture scan PASSED: 1323
reviewed identities, 1323 findings, zero unclassified/never-allowlisted. Historical
check-3.log failure (24 versus 21 schema statements) NOT REPRODUCED:
`uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
passed, 37 passed / 6 skipped (1200-second timeout). No ledger or code repair
is justified by either result. Local path search found no nested AGENTS.md in
scoped directories (rg exit 1 for no matches, not a validation failure). This file is the durable checkpoint for this single item.

## Fresh validation and architectural findings

All validation below ran with 1200-second timeouts:

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3277 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q`: 80 passed.
- `uv run pytest packages/maistro-server/tests/api/test_rate_limit.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: 27 passed.
- `uv run python scripts/check-backlog-consistency.py`: PASS, 168 items.
- `uv run python scripts/check-adr-index.py`: PASS.
- Exact vulture command above matches `.github/workflows/quality.yml:1078`.

Accepted ADR-081226-a66b preserves Run/NodeRun/Attempt lifecycle ownership;
ADR-081626-f383 explicitly does not authorize implicit lease-expiry takeover.
Reconcile the issue's reclaim wording with that boundary: observe supported
fencing, do not implement a competing scheduler or invent reclaim authority.
ADR-085 requires per-principal limits; it does not establish shared limiter state.

The historical schema failure is already repaired: the independent expected DDL
list in `packages/maistro-core/tests/persistence/test_pg_learnings.py:177–179`
includes all three Gauntlet audit fields. No test weakening or ledger edit needed.
The six skipped tests do not prove live PostgreSQL behavior.

Fresh executed counterexample: `tests/test_soak_promotion_gates.py:439` uses the
actual production RateLimitMiddleware on two ASGI instances with identical IP
and credentials. Both independently return [200, 200, 429]; switching replicas
increases the allowance. The test passes by demonstrating the acceptance gap,
not by proving deployed non-bypass. The middleware constructs an independent
InMemoryRateLimiter (`packages/maistro-server/src/maistro_server/api/rate_limit.py:93`).

The driver always rejects its own host-process artifact at
`scripts/soak/run_soak.py:744`; the four-hour rejection regression passes.
Its schedule probe cancels the admitted Run without physical execution
(`scripts/soak/run_soak.py:1067`). Duration cannot fix either limitation.

## Acceptance audit

| Issue criterion | Fresh evidence and disposition |
| --- | --- |
| Representative workload | Profile read; expressly excludes multiple users/Workspaces, fan-out, successful tools/models, Design/Canvas and Goal workers. Full criterion UNVERIFIED. |
| At least two production replicas | Tests use two ASGI middleware instances, not two deployed RC replicas. UNVERIFIED. |
| Sustained saturation, queues, reclaim, retries, leaks, shutdown | No sustained production load executed. UNVERIFIED; reclaim must respect accepted fencing ADR. |
| No duplicate physical work / Goal reconciliation | Admission-only probe cancels its Run without execution. Physical effects and Goal reconciliation UNVERIFIED. |
| Rate/security/degraded behavior, no replica-selection bypass | Independent production-middleware allowances reproduced by passing regression. Non-bypass NOT MET; full deployed security/degraded behavior UNVERIFIED. |
| Complete telemetry and thresholds | Profile distinguishes driver-loop lag from application-loop lag and local receipts from DB latency. Complete deployed telemetry UNVERIFIED. |
| Kill/restart during active work, drain/fencing/recovery | No active-work deployed restart executed. UNVERIFIED. |
| Long soak of exact RC/config, rerun after changes | Rejection test proves host preflight cannot certify RC even at four hours. Exact-RC soak UNVERIFIED. |
| Findings classified to earliest milestone | Backlog consistency passes; complete load-derived classification UNVERIFIED. No GitHub mutation. |
| Human/machine evidence bound to exact image/package/commit/config hashes | This report is local validation only, not a hash-bound production soak. UNVERIFIED. |

## Disposition

BLOCKED. Only this report changes; no new tests, so no inventory delta.
The requested CI gate and historical failing test are green without edits.
Speculative code/ledger repairs would not resolve the actual acceptance gaps.
No exact immutable RC/config was supplied as the promotion target, and this
preflight runner cannot produce that evidence. No promotion approval claimed.

Progress: checked 1 issue, done 0 acceptance-complete, skipped 0, failed
validation commands 0, blocked 1. Next: designate the immutable production
artifact/config; resolve aggregate rate-policy behavior at its canonical path;
exercise representative physical work and supported recovery on two deployed
replicas, then run the >=4-hour soak with complete hash-bound telemetry.
Do not repeat clean gate scans as a substitute for these prerequisites.
Commit this handoff locally; preserve all inherited work.
