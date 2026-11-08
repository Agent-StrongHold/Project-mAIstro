# Issue #860: bounded repair validation (47d55b89)

## Frozen scope

- Issue: #860 only; branch `auto-860`, starting HEAD
  `5f309a09a93466812fa3f0b09b6674961121553f`, supplied base
  `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
- Starting worktree is clean; no incoming uncommitted work to salvage.
- Evidence snapshot: supplied dispatch-context.json, prior result
  0fa5de17, prior failing check 98a11313/check-3.log. No check-*.log
  exists in this job's directory at entry. No GitHub queries or mutations.
- Files in scope: this report; `quality/vulture-baseline.json` only if the
  required scan identifies reviewed retained debt; schema-fence implementation
  and adjacent test (`packages/maistro-core/src/maistro/persistence/pg_learnings.py`,
  `packages/maistro-core/tests/persistence/test_pg_learnings.py`) if the supplied
  failure reproduces; `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, and existing load/evidence documentation
  for acceptance validation. Any test changes require a matching inventory note.
- Architecture/CI documentation and production paths referenced by those tests
  are read-only context. No changes to unrelated blockers or execution authority.

## Initial evidence and assumptions

The supplied prior failure was an ordered schema-DDL assertion (24 actual
statements versus 21 expected). The prior worker reported BLOCKED because the
runner cannot establish exact-RC equivalence and probes reproduce process-local
rate limits and receipts. These are claims to check, not readiness evidence.
The requested vulture amendment is conditional on actual scan findings; do not
change a passing ledger. No develop conflict exists at entry.

## Results

- Required vulture scan passed (1322 findings / 1322 reviewed identities;
  unclassified=0, never_allowlist=0). It selected trusted base `321cbdb8fe9b`.
  No ledger amendment is justified by this scan.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  tests/test_soak_promotion_gates.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`
  passed: **110 passed, 6 skipped in 2.20s**. This is one command (wrapped here
  for readability). The supplied failure does not reproduce: the expected DDL
  already includes validation-audit columns at test_pg_learnings.py:173–175.
  Production ensure_schema acquires the transaction/advisory fence before DDL
  at pg_learnings.py:215–222. Skipped tests provide no live PostgreSQL evidence.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3301 files formatted.
- `uv run python scripts/check-ratchet-provenance.py`: exited 0.
- Raw command logs are in the supplied job directory under `worker-*.log`.
  The vulture and provenance invocations match `.github/workflows/vulture-ratchet.yml`.
- Existing load profile explicitly calls the runner a preflight emulator and
  identifies missing representative workloads. Increasing its duration cannot
  establish production artifact equivalence.

## Production-path inspection and acceptance

Read accepted ADR-081226-69ee, ADR-081626-f383 and ADR-082526-b36a.
The latter supplies renewal/reclaim semantics beyond the earlier fencing ADR;
absence of soak evidence does not imply absence of those mechanisms. Preserve
Goal -> Graph -> Run -> NodeRun -> Attempt and the canonical lease owner. No
scheduler, execution, event or authorization authority was introduced.

Fresh tests execute the production RateLimitMiddleware: the same identity
receives `[200, 200, 429]` independently on each instance
(`tests/test_soak_promotion_gates.py:439`). Its constructor creates an
InMemoryRateLimiter per instance (`api/rate_limit.py:93`). The production task
router test records owner 200 / peer 404 (`tests/test_soak_promotion_gates.py:564`);
GET uses the injected queue (`api/tasks.py:144`). These are meaningful component
observations, not a claim about every possible deployed ingress configuration.

| Acceptance criterion | Executed evidence / disposition |
|---|---|
| Representative supported-release load profile | **UNVERIFIED**. Read the complete existing profile; its remaining-gaps section explicitly lacks concurrent users/Workspaces, fan-out, successful tools/models, Design/Canvas and background reconciliation coverage or RC-specific exclusions. |
| Two production application replicas | **UNVERIFIED**. Two-instance ASGI probes passed; no production Compose replicas were exercised this round. |
| Sustained saturation, queue growth, reclaim, retry, leak observations | **UNVERIFIED**. Focused tests are not sustained load. |
| No duplicate physical work / schedule, Run, Attempt, Goal fencing | **UNVERIFIED**. Admission evidence does not prove physical-work uniqueness; the profile's schedule probe cancels its queued Run. |
| Replica-resistant rate/security/degraded behavior | **UNVERIFIED** for deployment. Fresh tests reproduce independent replica allowances; local enforcement alone is insufficient. |
| Required PostgreSQL/application-loop/worker/RSS/fd/queue/error telemetry and thresholds | **UNVERIFIED**. Driver-loop lag is not application-loop latency; no fresh production telemetry captured. |
| Active-work kill/restart, drain, fencing and recovery | **UNVERIFIED**. No active physical Attempt fault injection executed. |
| Long soak of exact RC artifact/configuration | **BLOCKED / UNVERIFIED**. `scripts/soak/run_soak.py:744–755` returns exact_rc_artifact=false; promotion tests execute this fail-closed contract. No immutable RC image/configuration has been selected for this run. |
| Load findings classified before promotion | **UNVERIFIED** for completeness. Existing findings retained; no GitHub mutation permitted or performed. |
| Machine/human production evidence bound to exact hashes | **UNVERIFIED**. Source-bound component test logs are not image/package/configuration-bound soak evidence. |

## Handoff

**BLOCKED**, not merge-ready. Both the cited schema-test failure and the proposed
vulture debt repair are unsupported by fresh results. No production or ledger
change was made. Only this report changed; no test additions or inventory delta.
The worktree's existing implementation and evidence were preserved.

Next action requires an immutable RC image/configuration and a representative
production workload, then a >=4-hour production soak with application telemetry
and active Attempt failure/recovery evidence. The current emulator cannot supply
that acceptance evidence regardless of duration. Any later code/runtime-config
change requires a new soak. Repeating only these passing CI checks is not progress
toward production acceptance.

Progress: {checked: 1, done: 0, skipped: 0, errors: 0,
next: exact-RC production soak}. Local commit is a validation handoff only.

