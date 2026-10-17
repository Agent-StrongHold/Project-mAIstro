# Issue #860 — bounded repair bf875a39

## Frozen scope

- Issue: #860 only; branch `auto-860`.
- Starting HEAD: `e3b6f5b828596c259d2c70169f4cc01322f58818` (verified).
- Base: `3c761d14db944a727fa0744444bc67cfe36d49f7` (diff resolves).
- Clean incoming worktree; no salvage patch needed.
- Inspect: supplied dispatch snapshot, prior result and named failure log;
  repository instructions; relevant execution/production ADRs;
  `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`,
  `docs/testing/soak/m3a-load-profile.md`, adjacent production rate/admission code;
  vulture checker and identities only if its exact CI invocation fails.
- Candidate edits: demonstrated soak defect and adjacent regression/inventory
  note, this report, reviewed vulture ledger identities only if required.
- No GitHub mutation, no refetch, no deployment or promotion approval.

## Initial evidence / assumptions

Current job directory has no `check-*.log` files. The supplied prior result is
BLOCKED, not acceptance proof. Treat this as a writer repair and independently
run validation. An unspecified exact RC image/config cannot be replaced by a
host-process smoke run. Do not invent an artifact identity or new authority.

## Validation and acceptance

- Exact CI vulture invocation passed: 1323 reviewed identities / findings,
  zero unclassified or forbidden identities. No ledger amendment is warranted.
- Prior `check-3.log` fails on 24 schema statements versus 21 expected;
  current focused package tests pass: 38 passed, 6 skipped (live DB cases).
- Current soak tests: 65 passed. These are not an exact-RC soak.
- New reachable evidence: `one_request_with(kind="run_get")` constructs
  `task-soak-{seq % 500}` instead of reading a receipt returned by task admission.
  This contradicts the declared receipt-read class and makes that workload
  exercise not-found responses, not durable receipt reads. Inspect the actual
  task API before repairing this existing in-scope driver path.
- Production API inspection confirms POST returns `task_id` and GET reads
  `TaskQueue.get`, which is process-local, not a durable database lookup.
- Regression first failed on the old worker: real admission returned 202,
  but its admitting replica's read returned 404 instead of 200.
- Repaired worker retains at most 500 observed task identities; reads still go
  through the LB. Missing identities produce explicit status 0, never invented
  paths. Peer 404/503 responses remain in evidence.
- Added seven tests and `m3a-860-observed-receipt-reads.md` inventory delta.
  Focused suite: 72 passed. First focused lint caught a test closure binding
  (`B023`); replaced it with a replica factory before final validation.
- Complete targeted tests: 88 passed (soak/boot/secrets contracts), plus 38
  passed / 6 skipped (package persistence/admission). Inventory gate: 5274
  root tests, matching notes, no duplicate evidence. Documentation links pass.
- Root lint passed; format check requested wrapping the new receipt validation
  condition. Applied that wrap. Final output-path review found per-kind statuses
  were not previously serialized: publish the existing snapshot's counters under
  `thresholds.kind_status_codes`, including unseeded 0 and peer 404. Regression
  assertions verify those counters survive JSON serialization.

## Architecture reconciliation

Read repository instructions, documentation authority map, accepted
ADR-081226-a66b and ADR-081626-f383. Preserve Goal -> Graph -> Run -> NodeRun ->
Attempt. Receipt IDs retained by the load client are only bounded observations,
not a competing queue/store/scheduler. The real-router regression uses one
canonical admission spine and two receipt queues, with no execution runner.
Lease expiry takeover is not authorized by the accepted fencing ADR; issue
wording cannot implicitly introduce reclaim authority.

## Final commands and outcomes

All commands ran in the assigned worktree, with 600-second validation timeouts.

| Command | Outcome |
| --- | --- |
| `uv run pytest tests/test_soak_promotion_gates.py -k receipt_load -x -q` before repair | Expected regression failure: admitting replica returned 404, expected 200. |
| `uv run ruff check .` | Passed after fixing test closure binding. |
| `uv run ruff format --check .` | Passed, 3277 files, after wrapping the receipt validation condition. |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py -x -q` | 88 passed. |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 38 passed, 6 skipped. Database skips are not live-PG evidence. |
| `uv run python scripts/check-suite-inventory.py --suite tests/` | Passed: 5274 collected, expected 5274; no duplicated evidence. |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | Passed: 1323 reviewed / observed identities, zero unclassified or forbidden. No ledger change justified. |
| `uv run python scripts/check-doc-links.py` | Passed: 2683 markdown files, zero broken links. |
| `git diff --check` | Passed. |

Receipt status 0 is explicitly excluded from sent-request totals and latency
samples. The evidence includes `requests_not_sent` and per-kind status counters;
a single actual latency sample no longer raises in percentile calculation.
Historical packs cannot validate this modified workload; new live evidence is
required. No full-tree pytest or live production soak was claimed.

## Acceptance audit

| #860 criterion | Executed evidence / remaining limit |
| --- | --- |
| Representative workload | Receipt subprofile repaired; real-router regression proves observed IDs, same-principal reads and visible peer 404. Full concurrent users/Workspaces, fan-out, successful tool/model, Canvas and background-worker profile **UNVERIFIED**. |
| Two production replicas | Two ASGI instances are only a route contract probe; supported production topology **UNVERIFIED** this round. |
| Sustained load / saturation / reclaim / leaks | **UNVERIFIED**; no long-running load executed. Four-hour preflight rejection tests pass, not a four-hour soak. |
| No duplicate physical work / Goal reconciliation | **UNVERIFIED**. Admission tests pass, but the driver cancels its schedule probe rather than executing it; no physical-work or Goal oracle established here. |
| Rate/security/degraded behavior without replica-selection bypass | Existing executed production-middleware test demonstrates independent per-replica `[200,200,429]` allowances for one identity. Aggregate non-bypass is **NOT MET** by that behavior; exact-RC security/degraded concurrency **UNVERIFIED**. |
| Complete metrics / thresholds | Per-kind receipt counters now preserve 0/200/404/503 evidence; sampler regressions pass. Full application-loop, worker, pool and long-window threshold evidence **UNVERIFIED**. |
| Kill/restart with drain/fencing/recovery | **UNVERIFIED**; no live restart or physical Attempt recovery observation this round. |
| Long-running exact RC artifact/config | **UNVERIFIED / BLOCKED**. Executed CLI regressions reject missing/null/preflight artifacts even with synthetic four-hour duration. Current driver only boots host processes; an immutable designated RC and production-topology run remain required. |
| Findings filed/reclassified | Local receipt finding is a workload-validity defect plus a replica-visible receipt limitation, not proof of duplicate physical work. External filing/reclassification **UNVERIFIED**; GitHub mutation prohibited. |
| Machine/human evidence tied to exact artifact hashes | Profile/report and tested JSON counters updated locally. New hash-tied live RC evidence publication **UNVERIFIED**. |

## Changed files / handoff

- `scripts/soak/run_soak.py`: bounded observed receipt population; real receipt
  reads; explicit unsent accounting; serialized per-kind response counters.
- `tests/test_soak_promotion_gates.py`: seven regression cases including real
  production router/admission behavior and visible cross-instance receipt loss.
- `docs/testing/inventory-notes/m3a-860-observed-receipt-reads.md`: +7 root tests.
- `docs/testing/soak/m3a-load-profile.md`: correct receipt-read evidence contract
  and invalidate the historical fabricated-ID workload claim.
- This report.

**BLOCKED for issue acceptance**, not integration approval. Checked: 1 issue;
done: 1 bounded repair; skipped: 0 issues; errors: 0 remaining local validation
failures. Progress committed locally; no quality ledger/grant or production
execution authority changed.

Next: designate the immutable production RC configuration, complete the missing
representative workload/physical-work/metrics oracles within canonical authority,
resolve the rate-budget acceptance mismatch and investigate peer receipt visibility,
then run and publish the required long soak. Do not treat passing local checks or
another longer host-process preflight as promotion evidence.

