# Issue #860 — bounded CI repair, job 76d87a96

## Frozen scope

- Assigned item: #860 only; branch `auto-860`, clean starting HEAD
  `0716724f13298e3ff67464a040c6edffb7b94092`; supplied develop base
  `3c761d14db944a727fa0744444bc67cfe36d49f7` resolves locally.
- Inspect: supplied dispatch snapshot and prior result/log, repository instructions,
  relevant ADRs, `scripts/check-vulture-baseline.py`, its CI invocation,
  `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`,
  `docs/testing/soak/m3a-load-profile.md`, adjacent rate/backpressure tests.
- Potential edits: this report and `quality/vulture-baseline.json` only if the
  exact requested scan demonstrates retained unbanked identities. No speculative
  scanner repairs or unrelated issue work.
- Initial job-directory listing contains no `check-*.log`; supplied historical
  failure will be inspected and independently rerun.
- Ambiguity: dispatch calls this CI repair but prior result reports missing
  production soak evidence. Treat scanner repair and acceptance proof separately;
  do not manufacture an RC artifact/configuration or equate ASGI tests to soak.

## Progress

Starting tree is clean; no salvage patch required. Exact requested Vulture scan
passes: 1323 findings / 1323 reviewed identities, zero unclassified and
never-allowlist findings. No ledger edit is warranted. Historical `check-3.log`
is actually a schema-fence test failure (24 statements versus 21 expected),
not a Vulture failure. Independent regression validation passes (below).

## Executed validation

All commands used 1200-second timeouts (Vulture: 1000 seconds).

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, counts above; matches
  `.github/workflows/vulture-ratchet.yml:82`.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  **37 passed, 6 skipped**. Historical failure does not reproduce. The test at
  line 177 already covers the three validation-audit columns missing from the
  historical expectation. Production `ensure_schema` at line 215 acquires the
  transaction-scoped advisory lock before upgrades. Skips do not prove live
  PostgreSQL concurrency.
- `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py -x -q`:
  **89 passed**. Total: **126 passed, 6 skipped**.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3277 files.
- `uv run python scripts/check-doc-links.py`: PASS, 2689 Markdown files,
  zero broken relative links.
- `git diff --check`: PASS.

## Architecture and production evidence

Read repository instructions, documentation authority hierarchy, accepted
ADR-081226-a66b (Run lifecycle) and ADR-081626-f383 (Attempt fencing).
Preserve Goal -> Graph -> Run -> NodeRun -> Attempt; queue receipts do not own
execution lifecycle. The accepted fencing ADR explicitly leaves lease-expiry
reclaim undefined; this issue is not authority to invent a second scheduler or
implicit takeover semantics.

`scripts/soak/run_soak.py:744` unconditionally marks host preflight as not the
exact production Compose artifact. Existing executed tests enforce failure even
with simulated long-duration evidence. Extending this emulator's duration cannot
complete acceptance. `m3a-load-profile.md` explicitly lists coverage gaps and a
four-hour promotion minimum. No exact RC image/configuration is designated by
the assignment; no production soak was run or claimed this round.

The executed production middleware test at
`tests/test_soak_promotion_gates.py:439` observes 200/200/429 independently on
each instance for the same identity, for both authenticated and unauthenticated
cases. This matches the process-local contract at
`packages/maistro-server/src/maistro_server/api/rate_limit.py:32`, not a
cluster-wide allowance. The executed receipt-router test at line 564 observes
200 locally and 404 at the peer: production `api/tasks.py:144` reads `queue.get`.
Neither test is a deployed-replica or physical-work-deduplication proof.

## Acceptance disposition

| #860 criterion | Evidence / remaining gap |
| --- | --- |
| Representative RC workload | Profile inspected; multiple users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and Goal/background work absent. **UNVERIFIED**. |
| At least two production application replicas | Two ASGI instances tested, not two deployed RC replicas. **UNVERIFIED**. |
| Sustained saturation, queue growth, expiry/reclaim, retries, leaks, shutdown | Sampler/accounting tests pass; no sustained production run. **UNVERIFIED**. |
| No duplicated physical work for schedules/task/Run/Attempt/Goal | Admission tests are not physical-work oracles. **UNVERIFIED**. |
| Rate/security/degraded non-bypass | Local rate enforcement and retryable admission backpressure tested; replica selection increases aggregate allowance. Full requirement **UNVERIFIED**, needs explicit contract reconciliation. |
| Complete production metrics and thresholds | Partial sampler/gate tests pass; driver-loop lag is not application-loop lag. Full production metrics **UNVERIFIED**. |
| Kill/restart during active work with fencing/recovery | Boot tests pass, not active-work recovery. **UNVERIFIED**. |
| Long soak of exact RC artifact/configuration | Host preflight fails closed; no designated immutable RC or exact-RC runner supplied. **UNVERIFIED**, blocked. |
| Findings filed/reclassified before promotion | No new live-load findings asserted; GitHub mutation prohibited. **UNVERIFIED**. |
| Machine/human evidence tied to image/package/commit/config hashes | This report identifies tested source HEAD only, not production soak evidence. **UNVERIFIED**. |

## Handoff

**BLOCKED**: no reproduced CI repair target; exact-RC promotion evidence remains
missing. Do not amend an already exact ledger merely to produce a repair diff.
Only this report changes; no code, runtime configuration, gates, grants, ledgers,
or tests changed. No inventory delta. All earlier work preserved.

Next: release owner must designate the immutable RC and configuration, resolve
the process-local rate contract against acceptance, supply complete workload and
physical-work/metrics oracles, then execute the required production soak.
Repeating this same passing scanner cannot resolve these prerequisites.

Progress: checked 1, done 0, skipped 0, validation errors 0; next action is the
external acceptance prerequisite above. Local commit is handoff only.
