# Issue #860 CI repair checkpoint

## Frozen scope

- Assignment: issue #860 only, branch `auto-860`, starting HEAD
  `c08b527df17014b490fe5a928352614c1898ab29`, base
  `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
- Worktree was clean. No salvage required.
- Inspect existing soak implementation/tests/docs and relevant ADRs; run the
  requested exact vulture gate. Amend only evidenced retained identities or
  genuinely dead code and this validation report (inventory note only if tests change).
- No GitHub mutations, new execution authority, or promotion claims.
- Current job directory has no `check-*.log` files. Inspect supplied prior
  `check-3.log`; prior result reports BLOCKED and unverified production soak.
- Ambiguity: assignment is a writer CI-repair round, not a request to manufacture
  production evidence. Proceed with the explicit ledger-repair exception; retain
  any independently reproduced production blockers.

## Progress

Initial state and assignment verified. Acceptance criteria extracted from the
frozen dispatch issue body.

- Exact requested vulture command passed: 1322 reviewed identities, 1322
  findings, zero unclassified/never-allowlist findings. No ledger amendment is
  justified; the advertised CI debt is not present at the assigned HEAD.
- Supplied prior `check-3.log` fails the schema-fence test (24 statements versus
  21 expected). Current test already explicitly includes the three Gauntlet
  columns. Re-execution of `uv run pytest
  packages/maistro-core/tests/persistence/test_pg_learnings.py
  tests/test_soak_promotion_gates.py -x -q`: **109 passed, 6 skipped**.
- `uv run ruff check .`: passed. `uv run ruff format --check .`: passed,
  3301 files already formatted.
- No code/test/ledger edits warranted by these results.
- Inspected accepted ADR-081226-a66b (canonical lifecycle) and
  ADR-081626-f383 (durable Attempt fences). No competing scheduler/authority
  introduced. The latter explicitly does not establish lease-expiry reclaim;
  a schedule-admission race cannot stand in for physical-work recovery evidence.
  ADR-081 is Proposed, not an accepted waiver of issue acceptance.
- Production `api/rate_limit.py:95` constructs one in-memory limiter per
  middleware instance. Executed `test_replica_selection_has_an_independent_production_allowance`
  reproduces independent `[200, 200, 429]` allowances for each replica, for both
  authenticated and unauthenticated callers.
- Executed `test_receipt_load_reads_admitted_tasks_through_production_router`
  uses two real task queues with one canonical admitter: admission succeeds,
  owner reads 200, peer reads 404. This is an ASGI contract probe, not deployed
  multi-process soak evidence.
- One exploratory lookup used a nonexistent `middleware/rate_limit.py` path;
  recorded not found, skipped. The test import resolved the actual `api/` path.

## Acceptance review (not promotion approval)

| Issue criterion | Executed evidence / remaining gap |
| --- | --- |
| Representative profile | UNVERIFIED: `m3a-load-profile.md` explicitly lacks concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Canvas and background reconciliation. |
| At least two production replicas | UNVERIFIED: two ASGI instances were tested, not the production Compose artifact. |
| Sustained saturation, queues, leases, retries and leaks | UNVERIFIED: no sustained deployment run in this round; unit tests do not prove these observations. |
| No duplicated physical work; Goal reconciliation | UNVERIFIED: admission gates are tested, not physical Attempt execution/recovery under load. |
| Replica-resistant security/rate/degraded behavior | UNVERIFIED at acceptance level; independent production limiter allowances and peer receipt 404 reproduced. |
| Production telemetry with explicit thresholds | UNVERIFIED: documented thresholds/harness tests are not production measurements; driver-loop lag is not app-loop lag. |
| Kill/restart during active work, drain/fencing/recovery | UNVERIFIED: no deployed active-work restart in this round. |
| Long exact-RC soak | UNVERIFIED: `run_soak.py:744` deliberately rejects artifact equivalence for host-process preflight. |
| Findings classified to earliest invariant | UNVERIFIED for complete promotion coverage; known rate-limit/receipt gaps reproduced locally. No GitHub mutation performed. |
| Hash-bound machine/human soak evidence | UNVERIFIED for exact RC: this report is local validation, not a new production evidence pack. |

## Disposition

BLOCKED for issue acceptance, not a new CI repair failure. Do not schedule another
identical ledger-repair pass against this unchanged code: the supplied failure
is stale and the exact scanner passes. Next work requires a selected immutable
RC/configuration, a representative production-path workload and physical-work
instrumentation, then the documented long soak. Any change invalidates old soak
claims. Do not bypass the fail-closed preflight gate to obtain a green result.

No tests added or modified; no inventory delta required. Only this report changes.
Additional validation:

- `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  **1 passed**, production admission backpressure remains 429 + Retry-After.
- `uv run python scripts/check-adr-index.py`: passed.
- `uv run python scripts/check-suite-inventory.py --help`: inspected CLI only;
  inventory collection not run (no test changes).
- `git diff --check`: passed. No full-tree pytest run; service-backed coverage
  and the six skipped tests remain unverified.

Checkpoint: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "exact-RC production soak prerequisites"}`.
The sole issue remains blocked; CI revalidation is complete. Report committed
locally as the writer handoff, with no GitHub actions.
