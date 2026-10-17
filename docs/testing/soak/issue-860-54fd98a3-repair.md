# Issue #860 repair — job 54fd98a3

## Frozen scope

- Issue #860 only; worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD `6be2eaf995e015bf225c5555885ab8fa8cd06c07`; supplied develop base `2154f845347c9541016288c760f8da3f5cd2e064`.
- Clean initial worktree. No current-job `check-*.log` artifacts present.
- Evidence: supplied dispatch snapshot, prior result 401ed7a8, prior failed check 98a11313/check-3.log.
- Repair candidates frozen to `packages/maistro-core/tests/persistence/test_pg_learnings.py`, its production implementation `packages/maistro-core/src/maistro/persistence/pg_learnings.py`, `quality/vulture-baseline.json` only for reproduced reviewed CI identities, an associated inventory note if tests change, and this report.
- Read-only acceptance validation: existing `scripts/soak/` and `tests/test_soak*.py`, relevant architecture/ADRs and CI gates.

## Initial evidence and assumption

Prior check failed because the schema-fence test expected 21 DDL statements while production executed 24. Reproduce before changing anything. Prior BLOCKED report describes missing production soak proof, not a merge conflict; no develop merge is assumed necessary. Exact-RC production proof cannot be replaced by a host preflight or unit tests.

## Reproduced results

- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`: **37 passed, 6 skipped** (1.51s). The reported 21-versus-24 failure is already repaired at the starting HEAD: the test independently lists all three Gauntlet validation columns. No additional test or production edit justified.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: **passed**, 1323 reviewed identities / 1323 findings, zero unclassified. No ledger amendment justified.
- `scripts/soak/README.md`: not found; skipped. Use existing source/tests and documentation pointers, not an invented README.

- `uv run ruff check .`: **passed**.
- `uv run ruff format --check .`: **passed**, 3277 files already formatted.
- `uv run python scripts/check-backlog-consistency.py`: **passed**, 168 items.
- Source inspection: host preflight explicitly cannot sign promotion; production middleware regression checks independent allowances per replica. These are remaining acceptance gaps, not justification to amend the vulture ledger.

- `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs`: **81 passed** (2.38s). Includes real production rate-limiter ASGI instances, child-process metrics, admission/backpressure and fail-closed preflight CLI checks. Mocked traffic and ASGI instances are not deployed production replicas.
- All validation command batches used 1200-second timeouts.

## Architecture reconciliation

Read repository instructions, documentation authority map, load profile, production schema fence and adjacent tests, and Accepted ADR-081426-1f7c, ADR-081626-f383, ADR-085. Physical execution identity is Attempt, not an admitted Run; canonical lease authority stays in the Run store. Lease expiry/reclaim cannot be inferred from the fencing ADR, which explicitly leaves takeover undefined. Per-principal limiting cannot be certified as replica-selection non-bypass by observing independent process-local 429 responses. No competing scheduler, store, event or authorization path introduced.

## Acceptance evidence

| #860 criterion | Fresh evidence and disposition |
| --- | --- |
| Representative RC load profile | **UNVERIFIED**: `m3a-load-profile.md` explicitly lacks concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and background Goal reconciliation. No immutable promoted RC/config designated in this dispatch. |
| At least two deployed application replicas | **UNVERIFIED**: ASGI replica tests executed, but no deployed production RC pair exercised. |
| Sustained saturation, queue growth, reclaim, retries and leaks | **UNVERIFIED**: focused tests are not sustained production observations. Six database tests skipped. |
| No duplicate physical work, including Goal reconciliation | **UNVERIFIED**: `scripts/soak/run_soak.py:1067` cancels an admission probe that never executes physical work; admission counts are insufficient. |
| Security/degraded behavior and replica-selection non-bypass | **UNVERIFIED** as a production guarantee. Executed `tests/test_soak_promotion_gates.py:439` counterexample for both authenticated/anonymous identities: each production middleware instance independently returns `[200, 200, 429]` to the same identity. Local enforcement is not aggregate non-bypass. |
| Full telemetry with explicit thresholds | **UNVERIFIED**: process-group sampler regressions pass; no production query/application-loop/worker/queue time series collected. Driver loop lag does not measure application loop lag. |
| Active-work replica kill/restart, drain/fencing/recovery | **UNVERIFIED**: no live production active-work restart performed. Exit/rejoin alone cannot prove physical-work recovery. |
| Long-running exact-RC artifact/config soak | **UNVERIFIED**: `scripts/soak/run_soak.py:744` explicitly rejects host preflight as exact RC. Executed CLI regressions confirm missing/null/preflight artifact evidence fails even with synthetic four-hour duration. |
| Findings classified before final promotion | **UNVERIFIED** for completeness: backlog consistency passes (168 items), but no representative load experiment performed this round; no GitHub mutations. |
| Human/machine evidence tied to exact hashes | **UNVERIFIED** for production: this report binds source-validation evidence to starting HEAD, not to a promoted image/config and sustained observations. |

## Handoff

**BLOCKED**, not integration approval. The supplied stale CI failure is already repaired; the exact vulture scan has no unbanked identities. Do not modify working code or the ledger merely to manufacture a repair. Only this report changes; no tests added and no inventory delta needed. No source/runtime-config change or new production soak claimed.

Next: designate the immutable promoted RC/config, complete its representative workload and physical-work oracle, resolve replica-selection semantics, then run the qualifying production soak with active recovery and full telemetry. Repeating this stale test-failure dispatch cannot establish those criteria.

Progress: checked 1 issue; acceptance-complete 0; skipped 0 issues; command failures 0 (one nonexistent README lookup recorded above). Local report commit is the checkpoint. Inherited branch changes outside the frozen scope are not certified.
