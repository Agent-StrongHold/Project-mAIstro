# Issue #860 — repair checkpoint (1f6ad2a0)

## Frozen scope

- Worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting head `3e8f68e2910a096ed979c6b30679388cd11c7262`; supplied base
  `b1f17b8d6246d347f617fb2c0b969e6798e0152b`.
- One assigned item: #860, including the explicit exact-debt-ledger CI repair.
- Initial working tree clean; no salvage patch necessary.
- Inspect: supplied dispatch context and prior check-3.log; repository instructions,
  applicable ADRs, soak runner/profile/evidence/tests, vulture gate and ledger,
  production paths exercised by the soak. Changes limited to evidence-backed
  repairs in these paths and this report (inventory note if tests change).
- No check-*.log files are present in the current job directory. Use the supplied
  prior logs as historical evidence, then execute fresh validation.
- Prior BLOCKED verdict is not assumed correct. No GitHub mutations or alternate
  execution authority will be introduced.

## Progress

Fresh exact vulture scan PASS: 1332 findings / 1332 reviewed identities, zero
unclassified or forbidden. No ledger change is justified. Historical check-3
failed because the fence test expected 21 DDL operations but observed 24; fresh
`uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
PASS: 37 passed, 6 skipped. The reported failure is not reproduced.

Issue acceptance has ten criteria. The current profile explicitly describes a
host-process preflight, missing representative workload classes, independent
per-process rate limits, and no physical-work recovery oracle. Source and test inspection confirms independent
`InMemoryRateLimiter` instances; the executed same-identity two-instance tests
observe `[200, 200, 429]` on each replica independently. This is evidence against
replica-selection non-bypass, not a multi-replica deployment soak.

Fresh validation also PASS: ruff check; ruff format (3105 files); focused soak,
boot, gitleaksignore and task-backpressure tests (73 passed); suite inventory
(17 suites / 28173 unique identities); backlog consistency (168 items).
No tests changed, so no new inventory-delta note is required.

## Commands executed

All validation ran in the assigned worktree with 1200-second timeouts.

| Command | Outcome |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1332/1332 identities; exact workflow invocation from `.github/workflows/quality.yml:1013` |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped; no live PostgreSQL proof from skipped tests |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3105 files |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 73 passed |
| `uv run python scripts/check-suite-inventory.py` | PASS, 17 suites / 28173 unique identities, zero duplicate evidence |
| `uv run python scripts/check-backlog-consistency.py` | PASS, 168 items |
| `uv run python -` (import runner, evaluate preserved `m3a-round6-shakedown.json`, assert duration/artifact rejection) | PASS: observed 90.43 seconds; failures `sustain_duration`, `exact_rc_artifact`; current artifact check `ok=False` |
| `git diff --check` | PASS |

The last Python check re-evaluates historical evidence, not newly observed load.
No new soak, live multi-replica deployment, or DB integration run was performed.

## Architecture and acceptance

Accepted ADR-081226-69ee keeps Graph/Run/NodeRun/Attempt as the canonical spine.
Accepted ADR-081626-f383 places execution leases/fences in the Run store and
explicitly does not yet define lease-expiry takeover. A load runner must not
invent reclaim authority to satisfy issue wording. Accepted ADR-085 requires
principal-keyed rate limits. The production middleware's documented process-local
scope does not prove the issue's stronger replica-selection non-bypass criterion.
ADR-081 is Proposed, not an accepted waiver of exact-artifact evidence.
No architecture, authorization path, scheduler, or ownership contract changed.

| #860 criterion | Evidence and disposition |
| --- | --- |
| Representative RC profile covering users/Workspaces, fan-out, schedules, queue, tool/model calls, Design/Canvas and workers | UNVERIFIED. `m3a-load-profile.md` explicitly lists missing workload classes; source uses one-key preflight/degraded model traffic. No complete RC applicability justification supplied. |
| At least two production application replicas | UNVERIFIED. `deploy/docker-compose.prod.yml:17-78` defines two services; executed tests use ASGI limiter instances, not two running RC services. |
| Sustained saturation, growth, reclaim/retry, leaks and restart | UNVERIFIED. Real child-process sampler test passes, but this is not application saturation or long-window load. Lease reclaim must respect ADR-081626-f383. |
| No duplicated physical work for schedules/task/Run/Attempt/Goal reconciliation | UNVERIFIED. Admission probe tests check receipts; the real task router/backpressure test holds queued Runs without starting a runner. Neither proves physical Attempt/Goal recovery. |
| Effective rate/security/degraded behavior without replica-selection bypass | NOT MET by inspected production middleware and executed tests: `tests/test_soak_promotion_gates.py:439-488` observes independent `[200, 200, 429]` allowances on both instances for the same authenticated or unauthenticated identity. Broader sustained security/degraded behavior UNVERIFIED. |
| Full telemetry with explicit thresholds | UNVERIFIED. Sampler tests pass; `scripts/soak/run_soak.py:1523-1585` evaluates only a subset. Driver loop latency is not application loop latency; full pool/worker/error coverage is not proven. |
| Kill/restart during active work with drain/fencing/recovery | UNVERIFIED. Boot/cleanup tests pass, but no live active-work kill/restart with physical Attempt correlation executed. |
| Long-running exact RC artifact/configuration soak | NOT MET by available evaluated evidence. 90.43-second preserved preflight fails duration and artifact checks. `scripts/soak/run_soak.py:686-697` always rejects this host-process topology even at four hours. |
| Findings filed/reclassified before promotion | UNVERIFIED. Backlog consistency passes, but external filing/classification completeness is not proven; no GitHub mutations. |
| Publish machine/human evidence bound to exact image/package/commit/config hashes | UNVERIFIED. Preserved preflight evidence is not a fresh immutable RC/config soak. This report is validation evidence only. |

## Disposition and next prerequisites

**BLOCKED** for #860 acceptance. The assigned historical schema failure is already
absent: `test_pg_learnings.py:175-179` includes all three audit columns missing
from check-3.log's expectation. Current vulture evidence contains no unbanked
identities; changing the ledger would be speculative, despite permission to amend
it when needed. Only this report changed; all inherited code and evidence remain.

Do not repeat this obsolete CI repair without a fresh failing command. The next
round needs a selected immutable RC image and normalized config, representative
workload applicability, a resolution of the observed per-replica rate allowance,
and production physical-work/recovery oracles. Only then run the fresh >=4-hour
exact-artifact soak; extending this host preflight cannot satisfy the gate.

Progress: {checked: 1, done: 0, skipped: 0, errors: 0, next: RC prerequisites}.
Focused validation is complete; issue acceptance remains incomplete. Commit this
report locally; no integration approval, remote mutation, or issue closure.
