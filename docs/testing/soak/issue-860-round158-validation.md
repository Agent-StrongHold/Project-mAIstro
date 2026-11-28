# Issue #860 — round 158 validation (blocked disposition)

Snapshot: issue #860, branch `auto-860`, exact starting HEAD
`78534b6e33489634ef5fc194652c0f44faea9727`, merge base `fe733ae4ee27`
(develop base `2014ab888c0b`). Only this issue was processed. The supplied job
directory contains **no `check-*.log` files**, so every check below was
executed locally this round. No RC image, production configuration, or
authorized production target was supplied; recent issue comments are all
automation progress markers with no owner direction, waiver, or artifact.

## Executed validation (this round, HEAD 78534b6e)

- `uv run ruff check .` — pass. `uv run ruff format --check .` — pass (3474 files).
- `uv run pytest tests/test_soak_promotion_gates.py
  tests/test_gitleaksignore_contract.py tests/test_prod_stack_boot_contract.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  packages/maistro-core/tests/persistence/test_pg_learnings.py
  packages/maistro-core/tests/backlog/test_markdown_migration.py
  packages/maistro-core/tests/runs/test_execution_fencing.py
  packages/maistro-core/tests/graph/durable_runs/test_recovery_disposition.py -q`
  — **183 passed, 6 skipped** (one pre-existing Starlette deprecation warning).
- `uv run python scripts/check-suite-inventory.py` — ok, 21 suites match.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` (CI's exact arguments) —
  pass, 1309 reviewed identities = 1309 findings.
- `uv run python scripts/check-radon-baseline.py` — pass, 128 = 128.
- Integrity: `git diff fe733ae4..HEAD -- quality/` **empty** (no ledger
  edits); `git diff fe733ae4..HEAD -- .github/` **empty** (no workflow
  changes); 0 matches for `(fixes|closes|resolves) (#860|#89)` across all
  branch-only commit messages.
- Evidence-gate scan: every `docs/testing/soak/evidence/*.json` evaluated with
  the harness's own `run_soak.failed_promotion_checks` — **15 gate-bearing
  packs, 0 passing**; max observed sustain 420.1s (round-100..110 shakedowns)
  vs `PROMOTION_MIN_SUSTAIN_SECONDS = 14_400` (`scripts/soak/run_soak.py:69`,
  gate at 1625-1626); all shakedowns fail `exact_rc_artifact` because
  `preflight_artifact_check` (`scripts/soak/run_soak.py:744-755`) deliberately
  returns `ok=false` for host-process runs with no CLI override.

## Branch delta vs merge base fe733ae4 (re-verified)

Production source is limited to two #860-derived load-finding repairs, each
with new passing tests (suite inventory unchanged this round; no tests added
here):

- `packages/maistro-core/src/maistro/persistence/pg_learnings.py` (+22):
  transaction-scoped advisory lock (`_SCHEMA_LOCK_KEY = 0x6D61_656C`) fencing
  the boot-time DDL so two concurrently booting replicas cannot race
  `CREATE INDEX IF NOT EXISTS` into a duplicate-key crash (finding F7,
  observed live on pgvector/pg18). Tests: `test_pg_learnings.py` (+92).
- `packages/maistro-server/src/maistro_server/api/tasks.py` (17): task
  admission refusals return 429 with `Retry-After` instead of a 202 receipt or
  500 (finding F9). Tests: `test_tasks_concurrency_backpressure.py` (+118).

Everything else on the branch since the merge base is the soak harness
(`scripts/soak/`), contract tests (`tests/test_soak_promotion_gates.py` et al.),
and validation/round records.

## Acceptance disposition (unchanged by this round, now gate-verified)

1. Representative RC load profile — UNVERIFIED; `m3a-load-profile.md`
   self-declares its gaps (single API key; no Graph fan-out, successful
   tool/model work, Design/Canvas, Goal/background-worker coverage) as
   blockers, not waivers.
2. ≥2 production replicas — UNVERIFIED; component tests are not a deployed
   topology.
3. Sustained saturation/queue/lease/retry/leak/restart observation —
   UNVERIFIED; no pack exceeds 420.1s.
4. Exactly-once/fenced physical work across replicas — UNVERIFIED; no
   production-topology physical Attempt fencing evidence.
5. Rate limiting cannot be bypassed by replica selection — **NOT MET**:
   `packages/maistro-server/src/maistro_server/api/rate_limit.py` documents
   process-local enforcement (aggregate = N × configured, "deliberately NOT
   advertised as cluster-wide"), and the repo's own
   `test_replica_selection_has_an_independent_production_allowance`
   (`tests/test_soak_promotion_gates.py:477-527`) passes while demonstrating
   replica 2 granting a fresh `[200, 200, 429]` allowance after replica 1 is
   exhausted. Closing this needs an agreed shared per-principal budget
   contract/store at the existing middleware seam (a #842 contract extension
   with ADR backing); landing it here would also, per AC 8, itself require a
   new soak.
6. Metrics with explicit pass/fail thresholds — UNVERIFIED at promotion grade;
   threshold machinery exists in the harness but no qualifying production
   telemetry exists.
7. Kill/restart graceful drain/fencing/recovery — UNVERIFIED at promotion
   grade.
8. Long soak of the exact RC artifact/configuration — **BLOCKED**: no RC
   artifact or configuration was supplied, and the preflight refuses
   host-process evidence by design (correctly — loosening it would mint
   invalid evidence).
9. Findings filed/reclassified to earliest invariant — satisfied for the
   findings this branch generated (F7 → advisory-lock fence + tests; F9 → 429
   backpressure + tests); no production-load findings remain unfiled.
10. Machine- and human-readable hash-tied evidence — UNVERIFIED; no
    qualifying pack exists (0/15 by the harness's own gate).

## Disposition

**BLOCKED**, resolving the previous NEEDS-DEEP-REVIEW block into concrete,
reproducible prerequisites. This is not repairable by further tree edits in
this lane: ACs 1-4, 6-8, 10 require an owner-selected immutable RC
artifact/configuration, a production multi-replica target, and a ≥4-hour
representative run with active-work failure injection and hash-bound
telemetry; AC 5 additionally requires a shared-budget enforcement contract
decision at the #842 seam before any code could help — and any such runtime
change requires a new soak. The tree itself is healthy (all gates above pass),
the harness is honest by design, and weakening the 14,400s floor or the
exact-RC preflight to manufacture a pass would violate the issue's stop
condition. No source or test changes are claimed as repair this round; no
tests were added, so no suite-inventory note is required.

Next: an owner must (a) decide and land the shared per-principal rate-budget
contract (issue #842 scope, ADR-backed), then (b) supply the immutable RC
image/config and production target, then (c) run the representative ≥4-hour
multi-replica soak with kill/restart and publish the hash-tied evidence pack.
