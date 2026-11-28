# Issue #860 — round 110 (job 5f5a4f3f) independent verification of the round-109 repair

**Not promotion evidence or integration approval.** Round 109 performed the
actual repair (develop-base sync merged conflict-free as `5a59c724a`, fresh
battery + soak at the merged head) but its dispatch job (2ac23a43) died on a
provider timeout before any verifier or writer step ran. This round is the
independent verification the dead job never produced: every round-109 claim
was re-checked against reachable production behavior at the current head,
with a fresh deterministic battery. Zero source, test, or ledger edits were
made; the only tree content added is this record.

## Snapshot

- Start head `3b378e497` (round-109 lineage), tree clean, exactly the
  dispatched head. End head: same + this record.
- The dispatch job directory contained **no `check-*.log` files**: the driver
  executed zero deterministic checks. Every result below was executed fresh
  in this round at `3b378e497` and logged as `check-*.log` in
  `/home/dev/maistro/jobs/5f5a4f3f2cf24cfc9ce8444d0d357b52/`.
- `git fetch origin`: `origin/develop` is still `ab8b3737f` — the declared
  base, already an ancestor of HEAD (merge-base = `ab8b3737f`). **No new
  develop drift; no sync needed.**
- `git diff --stat 5a59c724a..3b378e497`: docs-only (4 evidence/handoff
  files, +549/-0). The production identity soaked in round 109 is byte-for-
  byte the production identity at the current head; no re-soak was required
  to keep the evidence binding valid.

## Round-109 claims re-verified (all confirmed)

1. **Prior failure resolved.** The last substantive validation failure on
   record (job 98a11313 `check-3.log`:
   `test_pg_learnings.py::test_ensure_schema_fences_ddl_behind_advisory_lock`,
   24 vs 21 DDL calls) does not reproduce at this head:
   `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -q`
   → **37 passed, 6 skipped** (skips require `MAISTRO_TEST_PG_DSN`)
   (check-5). Resolved by the develop merge that brought #1627's tree state.
2. **Battery at `3b378e497`, all green (this round).**
   - `uv sync --locked --extra dev` ok (check-0).
   - `uv run ruff check .` → All checks passed (check-1).
   - `uv run ruff format --check .` → 3,301 files already formatted (check-2).
   - `uv run python scripts/check-vulture-baseline.py packages/*/src
     --min-confidence 60 --exclude '*/third_party/*'` (quality.yml CI-exact)
     → rc=0: **1,322 reviewed identities → 1,322 findings**, `unclassified: 0`,
     `never_allowlist: 0`; ratchet base `ab8b3737fa64`, candidate
     `3b378e497c31`; no ledger amendment (check-3).
   - `uv run pytest tests/test_soak_promotion_gates.py
     packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
     tests/test_gitleaksignore_contract.py tests/test_prod_stack_boot_contract.py -q`
     → **89 passed** (check-4), including the row-5 regression lock
     `test_replica_selection_has_an_independent_production_allowance`
     (tests/test_soak_promotion_gates.py:439).
   - `uv run mypy` (ci.yml exact ten package srcs) → **Success: no issues
     found in 1057 source files** (check-6) — byte-identical to the round-109
     claim.
   - `uv run python scripts/check-suite-inventory.py` → ok: **17/17 suites**
     match recorded inventory, 0 duplicate/byte-identical evidence (check-7).
3. **Evidence pack integrity** (`docs/testing/soak/evidence/
   m3a-round109-shakedown.json`):
   - `hashes.git_head = 5a59c724a20e…`, `git_clean = true`,
     `git_diff_sha256`/`git_status_sha256` = empty-tree sha — the run was
     executed on a clean tree at the merge commit, as claimed.
   - Rendered nginx conf on disk sha256
     `86291c53ab2a81fdac9e89bc4d5902bd2049039047bd0cd527e24116b19467e1`
     **matches** `hashes.nginx_rendered_conf_sha256` (recomputed this round).
   - Functional records re-read from the pack and confirmed: exactly-once
     task admission 12×202 → 1 distinct run id (`duplicate_run_ids: 11`);
     schedule occurrence race `occurrences_with_multiple_runs: 0`;
     kill/restart SIGTERM drained 1.0 s with `drain_5xx: 0`,
     `drain_conn_errors: 0`, `escalated: false`, rejoined true;
     `task_admission_availability` ratio 1.0 (2,764/2,764, 0 unretryable
     429s); rate limit burst to 429 with `Retry-After` + `x-ratelimit-*` on
     all six probe paths with per-replica independent allowed counts (200 vs
     226 authenticated direct) — the process-local scope product fact.
   - `m3a-round109-shakedown-lb.log` contains **zero 5xx lines** (only the
     expected connect-refused entries inside the kill window, absorbed by
     nginx passive health checks).
4. **Promotion gates reproduced live** (check-8-soak): loading
   `failed_promotion_checks` from `scripts/soak/run_soak.py` at this head and
   applying it to the round-109 pack exits 1 with exactly
   **`['sustain_duration', 'exact_rc_artifact']`** — identical to the
   round-109 claim. `PROMOTION_MIN_SUSTAIN_SECONDS = 14400` vs observed
   `sustain_seconds: 420.05`; `exact_rc_artifact` fails by design for
   host-preflight topology ("not the exact production Compose image and
   configuration").

## Disposition (unchanged from round 109)

- **Row 3** (`sustain_duration` ≥ 14,400 s) — externally blocked: any
  in-lane round window is ~minutes; background execution is prohibited; no
  production Compose runner is designated in-lane.
- **Row 8** (`exact_rc_artifact`) — externally blocked: no RC exists to
  soak. Parent **#89 open**; RC PR **#1672 open draft**;
  #1567/#1602/#2100 are merged history, none a designation. Any soak at the
  eventual promotion commit remains required regardless.
- **Row 5** — contrary product evidence, unchanged: the aggregate budget is
  not enforceable via replica selection with the process-local
  `InMemoryRateLimiter`
  (packages/maistro-server/src/maistro_server/api/rate_limit.py);
  re-observed under load in rounds 100/106/107/108/109 and now verified
  third-hand; requires a product change, not soak evidence.
- Rows 1-2, 4, 6-7, 10 carry verified bounded evidence at the merged head
  and must be re-evidenced at the eventual promotion commit.
- Filing findings on GitHub is prohibited in this lane; the F1-F12 mapping
  to earliest broken invariants stays in-repo.

Progress: checked 1 issue; done 0 acceptance-complete issues (rows 3, 5, 8
blocked or contrary); skipped 0; validation errors 0; escalated 1 (RC
designation under parent #89); inventory delta 0 (no tests added or removed
by this round; the harness note
`docs/testing/inventory-notes/m3a-860-multi-replica-soak.md` already covers
the tooling); repairs 0 (round-109's repair verified intact; nothing to
re-repair).
