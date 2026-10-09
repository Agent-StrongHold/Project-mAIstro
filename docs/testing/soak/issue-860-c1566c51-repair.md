# Issue #860 — c1566c51 repair checkpoint

## Frozen scope

- One assigned item: #860 on `auto-860`, starting at
  `1f6109b7f07170e8c085f8ca030ea19882a57e0d`, supplied base
  `c91e354f30ca1fcc21ea97e1fa1bcf1f867bf508` (both resolve).
- Starting worktree is clean; no incoming edits to salvage.
- Inspect existing soak profile/evidence, harness and adjacent promotion tests,
  production rate middleware, and applicable deployment/execution/rate ADRs.
- Execute the explicitly assigned Vulture identity gate. Amend its ledger only
  if actual output identifies reviewed retained debt; do not guess findings.
- Permitted changes: this report, evidence-backed corrections to existing soak
  documentation, and Vulture repair files only if the gate demonstrates a defect.
  No production redesign or replacement execution authority.
- No `check-*.log` files were present in the supplied job-directory snapshot.
  Prior result was BLOCKED; its claims are not treated as fresh validation.

## Ambiguity and assumption

This is a writer/repair assignment (local commit required), not a read-only
verifier assignment. No promotable RC image digest or frozen production runtime
configuration is supplied. Do not invent either or certify host preflight as
production soak evidence. External filing is prohibited; report local findings
and leave external filing unverified.

## Progress

- Prescribed Vulture gate PASS: 1372 findings, 1372 reviewed identities,
  unclassified=0, never_allowlist=0; trusted base `c91e354f30ca`, candidate
  `1f6109b7f071`. No ledger repair is evidenced; ledger unchanged.
- Current evidence summary already retracts the prior shared-limiter claim.
  `RateLimitMiddleware` constructs independent in-memory counters per instance;
  existing production-middleware tests explicitly assert a second allowance
  on replica selection. Rewriting the already-corrected summary is not a repair.
- Accepted ADR-081426-1f7c identifies physical execution by Attempt ID;
  ADR-081626-f383 puts lease/fence authority in the Run store;
  ADR-082126-f69c forbids a second schedule runtime. Admission-only counts
  cannot prove physical work uniqueness. ADR-085's principal rate policy is
  not evidence of a shared limiter. Deployment ADR-081 is Proposed.
- Profile explicitly lacks users/Workspaces, fan-out, successful tool/model,
  Design/Canvas and Goal/background reconciliation coverage. No acceptance
  waiver is inferred from those omissions.
- Reachable production wiring: `maistro_server/main.py:588` installs the
  tested middleware; `api/tasks.py:117` maps canonical concurrency rejection
  to 429; `pg_learnings.py:141` takes the schema advisory lock. Existing tests
  cover the real middleware and task router, not just fabricated verdicts.

## Executed validation

Commands used 600–1200-second timeouts. Logs are in the supplied job directory;
these are worker logs, not nonexistent driver `check-*.log` results.

| Command | Outcome |
|---|---|
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; 1372/1372, no ledger drift (tool transcript) |
| `uv run ruff check .` | PASS (`worker-ruff.log`) |
| `uv run ruff format --check .` | PASS; 2712 files (`worker-format.log`) |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs` | 88 passed, 5 skipped, 92.59s (`worker-pytest.log`) |
| `uv run python scripts/check-compose-secrets.py` | PASS; 8 tracked Compose files (`worker-compose.log`) |
| `uv run python scripts/check-suite-inventory.py --suite tests/` | PASS; 4320 cases (`worker-inventory.log`) |
| `uv run python -` importing current `failed_promotion_checks` and evaluating the four existing JSON packs | PASS: all four rejected for duration and exact artifact (`worker-evidence.log`, including SHA-256 hashes) |

The five skipped tests require `MAISTRO_TEST_PG_DSN`. No live database race or
production soak is claimed. No tests were added or changed, so no inventory delta
is required. The executed suite includes live Linux child-process sampling and
both authenticated/unauthenticated independent-allowance middleware regressions.

Historical pack results: run 5 = 90.17s, run 6 = 90.43s, against 14400s minimum;
the two older packs lack top-level duration. All four lack a passing exact-RC
artifact gate. Raw packs were not modified. The current runner emits the failed
artifact check on its real output path (`run_soak.py:1465`), not only in tests.

## Acceptance disposition

| Criterion | Evidence and disposition |
|---|---|
| Representative RC profile | PARTIAL: documented request mix/thresholds, but explicit workload gaps at `m3a-load-profile.md:152`. Representative completeness UNVERIFIED. |
| Two application replicas | Compose declares two services; boot/config contract tests pass. Exact-RC two-replica execution UNVERIFIED. |
| Sustained saturation, queue growth, leases, retries, leaks, shutdown | Historical packs fail current duration gate. Long-window observations UNVERIFIED. |
| Schedule/task/Run/Attempt physical-work uniqueness and Goal reconciliation | Admission oracle regressions pass; schedule probe cancels its unexecuted Run. Cross-replica physical work/fencing and Goal reconciliation UNVERIFIED. |
| Security/degraded behavior, replica-selection non-bypass | NOT MET: executed real middleware regression asserts `[200,200,429]` independently on each replica for the same identity (`test_soak_promotion_gates.py:480-486`). Full concurrent security/degraded soak UNVERIFIED. |
| Complete telemetry and thresholds | Child-resource sampling regression passes; application-loop latency, complete worker census, sustained pool/lock/query/error telemetry and thresholds UNVERIFIED. |
| Kill/restart during active work with drain/fencing/recovery | Historical process exit/rejoin is insufficient to prove physical Attempt recovery. UNVERIFIED. |
| Long-running exact RC artifact/configuration | All four packs fail duration/artifact gates; host runner explicitly cannot qualify. UNVERIFIED. |
| Findings filed/reclassified before promotion | Existing local classifications retained. No fresh load findings claimed. External filing UNVERIFIED; GitHub mutations prohibited. |
| Machine/human evidence with exact hashes | Existing pack SHA-256 hashes freshly captured; no qualifying new image/config-bound production soak. UNVERIFIED. |

## Handoff

**BLOCKED**, not integration approval. The prior H3 wording defect is already
corrected; the requested Vulture defect does not reproduce. Only this report
changed. No production code, runtime configuration, tests, ledger, grants or
historical raw evidence changed.

The missing release prerequisites cannot be resolved by another short host run:
select the immutable RC image and frozen production configuration/model gateway;
resolve the per-process rate-policy mismatch with #860 non-bypass acceptance;
provide representative production-path workloads, physical Attempt/fence/recovery
oracles and complete telemetry; then execute at least 14400 seconds on the exact
artifact. Any later code/runtime-config change requires another soak. Do not
invent an RC identity or introduce a competing scheduler/store/authorization path.

Checkpoint: checked 1, done 0 acceptance-complete issues, skipped 0 assigned items,
errors 0 validation-command failures. Next: release prerequisites and an actual
exact-RC soak. This validation report is the local commit's sole changed file.
