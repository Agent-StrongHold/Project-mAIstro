# Issue #860 — round 101 (job b4ac5651) independent re-validation at 7afae7679

**Not promotion evidence or integration approval.** This round re-verified the
round-100 state independently — no prior verification claim was taken on
trust — and found nothing new to repair. The only change is this note.

## Snapshot

- Head `7afae767910d9c12fa7e901515cf696f4ae0cc18`, tree clean before and after
  this round's note commit; base `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- `git diff --name-only ed0fe24a07a0..HEAD` is exactly the four round-100
  evidence/handoff docs; **production source (`packages/ scripts/ tests/
  deploy/`) is byte-identical to the soak head**, so the round-100 evidence
  binding (`hashes.git_head = ed0fe24a0…`, `git_clean = true`) remains valid
  at this head.
- This job directory contains **no `check-*.log` files** (verified by
  listing); the referenced prior failure is the historical
  `98a11313/check-3.log`, treated as a claim and re-executed below.

## Re-executed deterministic battery at `7afae7679` (all green, this round)

| Gate | Result |
| --- | --- |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -q` | **38 passed, 6 skipped** — the `98a11313/check-3.log` failure (`assert 24 == 21`) does not reproduce |
| `uv run ruff check .` / `uv run ruff format --check .` | All checks passed / 3,277 files already formatted |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_gitleaksignore_contract.py tests/test_prod_stack_boot_contract.py -q` | **81 passed** (includes `test_replica_selection_has_an_independent_production_allowance`) |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (CI's exact arguments) | rc=0: **1,323 reviewed identities → 1,323 findings**, `unclassified: 0`, `never_allowlist: 0` — no ledger amendment |
| `uv run python scripts/check-radon-baseline.py` | **137 reviewed C-or-worse blocks → 137** |
| `uv run python scripts/check-suite-inventory.py` | ok: **17/17 suites** — inventory delta 0 (no test nodes added or removed this round) |
| `uv run python scripts/check-backlog-consistency.py` | OK: 168 items |
| `scripts/check-shipped-surface-truth.py` / `check-promotion-surface.py` / `check-release-consistency.py` / `check-merge-markers.py` / `check-doc-links.py` / `git diff --check` | Matrix complete / ok / released none, shipping 0.9.0, working toward 1.0.0 / no conflict markers / 0 broken links / clean |

## Round-100 evidence pack re-verified from the harness code, not the prose

`failed_promotion_checks()` was imported from `scripts/soak/run_soak.py` at
this head and applied to the committed packs:

- `evidence/m3a-round100-shakedown.json` → exactly
  **`['sustain_duration', 'exact_rc_artifact']`**
- `evidence/m3a-round44-shakedown.json` → the identical pair

Pack contents spot-checked: `sustain_seconds = 420.04` of 55,289 LB-issued
requests; 12 concurrent duplicate-`Idempotency-Key` submissions → 1 distinct
run id (`duplicate_run_ids: 11`); SIGTERM drain 1.5 s with `drain_5xx: 0`,
`drain_conn_errors: 0`, `escalated: false`, `rejoined: true`; FDs 30→37/29→35
with recorded maxima 40/39; postgres image pinned by digest.

## Terminal blockers unchanged and external — verified by construction

- **`sustain_duration`**: `PROMOTION_MIN_SUSTAIN_SECONDS = 14_400`
  (`scripts/soak/run_soak.py:67`) vs the 5,400 s lane timeout, with background
  execution prohibited. Not reachable from any in-lane round.
- **`exact_rc_artifact`**: `preflight_artifact_check()`
  (`scripts/soak/run_soak.py:730`) hard-fails host-preflight topology
  ("deliberately no CLI override"). No RC designation exists: parent #89 is
  open (RC built "only from the candidate commit"), #1567/#1602 are closed and
  #1672 is an open draft.

This remains an escalation to the release owner under parent #89 (RC freeze,
production Compose runner, ≥ 4 h soak window, provider keys, rate-limit
ownership decision) — not a code, test, or gate defect.

Progress: checked 1 issue; done 0 acceptance-complete issues (8/10 rows
evidenced fresh and re-verified, 2 externally blocked); skipped 0; validation
errors 0; escalated 1 (RC designation under parent #89); inventory delta 0.
