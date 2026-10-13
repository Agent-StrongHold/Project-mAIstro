# Issue #860 — bounded CI repair (f4bda920)

## Frozen scope

- Issue: #860 only; branch `auto-860`.
- Starting HEAD: `9ea3839d09cbab428e6ea18b252ca000d179164b` (resolved, clean).
- Supplied base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Process only the supplied dispatch snapshot; no GitHub mutations or refresh.
- Write scope: this report and `quality/vulture-baseline.json` only if the exact
  prescribed scan reports reviewed retained identities. No speculative fixes.
- Read/validation scope: repository instructions, relevant ADRs, the assigned
  prior failure log/result, soak runner/profile/promotion tests, adjacent
  production task/rate-limit code and tests, vulture gate and CI configuration.

## Initial observations

The current job directory contains no `check-*.log` files at initial inspection.
The supplied prior result reports BLOCKED, including independent replica rate
allowances and missing exact-RC long-soak evidence; those claims are not treated
as fresh verification. No merge conflict or uncommitted work exists to salvage.
Assumption: this is the explicitly assigned CI-repair round, not authorization
to replace canonical stores, scheduler, rate policy, or execution authority.

## Recorded validation

- Exact prescribed vulture scan: exit 0; 1323 reviewed identities and 1323
  findings, zero unclassified or forbidden identities. No ledger edit is
  justified; the requested unbanked-identity repair is not reproducible.
- Supplied prior `check-3.log` is a schema-fence test failure (24 observed DDL
  statements versus 21 expected), not a vulture failure. Revalidate the current
  schema test rather than amending an unrelated ledger.

- Focused pytest (schema persistence, task backpressure, soak promotion,
  production boot and secrets contracts): **126 passed, 6 skipped** in 2.69s.
  Thus the supplied historical schema-count failure does not reproduce at HEAD.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed (3277 files).
- `git diff --check`: passed.
- Profile review explicitly identifies the current runner as host-process
  preflight, not the promoted Compose image/config; it documents missing
  representative workloads and physical-work oracles. No live soak was run.

- `uv run python scripts/check-suite-inventory.py --suite tests/`: passed,
  5274 tests matching inventory, zero duplicate evidence. No tests changed;
  no inventory delta is needed.
- `uv run python scripts/check-doc-links.py`: passed, 2684 Markdown files,
  zero broken relative links.

Exact focused pytest command (1200-second timeout):

```bash
uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py -x -q
```

Exact vulture invocation, matching `.github/workflows/quality.yml:1078`:

```bash
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
```

Raw outputs remain in `/tmp/860-f4bda920-{vulture,pytest,inventory,doc-links}.log`.
The validation does not claim skipped database cases as live PostgreSQL proof.

## Architecture and reachable evidence

Read accepted ADR-081226-a66b (Run/NodeRun/Attempt lifecycle) and
ADR-081626-f383 (Attempt execution fencing). Preserve
Goal -> Graph -> Run -> NodeRun -> Attempt; queue receipts cannot become another
execution authority. The fencing ADR explicitly leaves expiry takeover outside
its current contract: issue wording about reclaim is not permission to add it.

- `scripts/soak/run_soak.py:744` returns `ok: false` for the exact-RC artifact
  check. The executed CLI tests at `tests/test_soak_promotion_gates.py:105`
  reject missing, null and preflight artifact records even with a synthetic
  four-hour duration. They exercise the CLI but substitute the completed run;
  they do not execute four hours of load.
- `packages/maistro-server/src/maistro_server/api/rate_limit.py:31` documents
  process-local budgets; its middleware constructs a separate limiter per
  instance. The executed test at `tests/test_soak_promotion_gates.py:439`
  obtains `[200, 200, 429]` from each instance for the same identity, for both
  credentialed and pre-auth requests. Local enforcement is proven; a shared
  principal budget/non-bypass by replica selection is not.
- `packages/maistro-server/src/maistro_server/api/tasks.py:147` reads the
  local queue. The executed real-router test at
  `tests/test_soak_promotion_gates.py:564` observes a successful receipt read
  on its admitting instance and 404 on the peer. This is an ASGI probe, not
  production topology, and does not prove physical execution duplication.
- `packages/maistro-core/tests/persistence/test_pg_learnings.py:177` already
  includes the three audit columns missing in the historical failure. Its
  independent ordered-DDL/fence assertion passes; do not weaken the test or
  make unrelated ledger edits to address a stale log.

## Every issue acceptance criterion

| Criterion | Fresh evidence and limit |
| --- | --- |
| Representative RC load profile | Reviewed `m3a-load-profile.md`; receipt load and counter tests passed. Concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and background work remain **UNVERIFIED** as a complete supported profile. |
| At least two production replicas | Tests exercise two ASGI instances; production-image replicas **UNVERIFIED**. |
| Sustained saturation, growth, expiry/reclaim, backoff, leaks and shutdown | **UNVERIFIED**; no sustained load executed. Process-group sampler tests pass, not long-window resource proof. Reclaim requires ADR-compatible authority. |
| No duplicate physical work, schedule/task/Run/Attempt admission and Goal reconciliation | Admission evidence-validation tests pass, but physical execution, Goal reconciliation and multi-replica fencing **UNVERIFIED**. |
| Rate/security/degraded concurrency cannot be bypassed by replica selection | Production middleware tests demonstrate independent budgets; stronger aggregate non-bypass claim **NOT MET** by those observations. Exact-RC concurrent security/degradation **UNVERIFIED**. |
| Complete metrics with explicit thresholds | Driver/counter/process sampler regressions pass; complete live PG usage/latency/locks, application loop lag, workers, RSS/fds, queue and error-rate threshold proof **UNVERIFIED**. |
| Kill/restart during active work, drain/fencing/recovery | Cleanup/drain evidence-gate tests pass; live physical-work kill/restart recovery **UNVERIFIED**. |
| Long-running exact RC artifact/config; repeat on changes | **UNVERIFIED / BLOCKED**; preflight correctly refuses promotion. No designated immutable RC/config was supplied for this run. |
| File/reclassify load findings before promotion | Local limitations recorded here and in existing profile; external filing/reclassification **UNVERIFIED**, GitHub mutation prohibited. No new under-load finding claimed. |
| Publish machine/human evidence tied to exact image/package/commit/config hashes | Local validation report only; new hash-tied exact-RC soak evidence **UNVERIFIED**. |

## Disposition and handoff

**BLOCKED**, not promotion or integration approval. The requested CI failure is
not reproducible at the assigned HEAD; no production code, tests, gates, grants,
or ledger are changed. Only this report is added and committed locally.

Progress: checked 1 issue; completed 0 issue acceptances; skipped 0 issues;
0 fresh validation failures. Stop rather than repeating the existing hundreds
of preflight/report rounds or inventing a scanner repair.

Next requires an owner-designated immutable RC deployment/configuration and a
production-topology driver with the missing workload, physical-work and metric
oracles. Resolve the documented rate-budget acceptance mismatch and peer receipt
visibility through the canonical architecture, then execute the required long
soak and publish hash-tied evidence. A passing vulture scan and local tests cannot
resolve those release-evidence prerequisites.
