# Issue #860 — round 103 (job 6fad315c) independent re-validation at 051eb0f2

**Not promotion evidence or integration approval.** This round resolves the
previous block ("worker requested attention: NEEDS-DEEP-REVIEW" after a
provider-timeout job) by independent re-execution: every deterministic claim
of rounds 100–102 was re-run at this head without taking any prior
verification on trust. No repair was needed; the only change is this note.

## Snapshot

- Head `051eb0f22b1361e2337ddd8c1d6720ff5e0efd56`, tree clean before and
  after this note commit; base `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- This job directory contains **no `check-*.log` files** (verified by
  listing); the referenced prior validation failure is the historical
  `98a11313/check-3.log` at verify head `872fd2cea` — treated as a claim and
  re-executed below. The intervening job `97de083c` was a provider timeout
  (`failure_kind: provider_error`, no checks produced).
- `git diff --name-only ed0fe24a07a0..HEAD -- packages scripts tests deploy`
  is empty: production source is byte-identical to the soak head, so the
  round-100 evidence binding (`hashes.git_head = ed0fe24a0…`,
  `git_clean = true`) remains valid at this head.

## Re-executed deterministic battery at `051eb0f2` (all green, this round)

| Gate | Result |
| --- | --- |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -q` | **38 passed, 6 skipped** — the `98a11313/check-3.log` failure (`assert 24 == 21`) does not reproduce |
| `uv run ruff check .` / `uv run ruff format --check .` | All checks passed / 3,277 files already formatted |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_gitleaksignore_contract.py tests/test_prod_stack_boot_contract.py -q` | **81 passed** |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (CI's exact arguments) | rc=0: **1,323 reviewed identities → 1,323 findings** (base `3c761d14db94`, candidate `051eb0f22b13`) — no ledger amendment |
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

Pack contents re-read directly this round: `exactly_once_tasks` — 12
concurrent duplicate-`Idempotency-Key` submissions → 12 × 202 → 1 distinct
run id (`ce8730ee…`, `duplicate_run_ids: 11`, cause `ok`);
`exactly_once_schedule_claim` — `occurrences_with_multiple_runs: 0`;
`rate_limit` — six-path probe, direct replicas bursting 800 requests to
200×200 + 600×429 with `x-ratelimit-*`/`Retry-After` headers;
`kill_restart` — SIGTERM drain 1.5 s with `drain_5xx: 0`,
`drain_conn_errors: 0`, `escalated: false`, `rejoined: true`;
`thresholds.checks.fd_growth` — 30→37 (max 40) / 29→35 (max 39);
`task_admission_availability` — ratio 1.0 (2,640/2,640 outside the kill
window, 0 unretryable 429s); `nonterminal_runs_after_settle` — count 0;
`hashes.postgres_image` pinned by digest.

## Terminal blockers unchanged and external — verified by construction

- **`sustain_duration`**: `PROMOTION_MIN_SUSTAIN_SECONDS = 14_400`
  (`scripts/soak/run_soak.py:67`) vs the 5,400 s lane timeout, with
  background execution prohibited. Not reachable from any in-lane round; the
  pack records 420 s sustained against that requirement.
- **`exact_rc_artifact`**: `preflight_artifact_check()`
  (`scripts/soak/run_soak.py:729`) returns `ok: false` for the
  host-uvicorn-preflight topology with "deliberately no CLI override". No RC
  designation exists: parent #89 is open, #1567/#1602 are closed and #1672 is
  an open draft.

Escalation to the release owner under parent #89 is unchanged (RC freeze,
production Compose runner, ≥ 4 h soak window, provider keys, rate-limit
ownership decision). The load profile (`m3a-load-profile.md`, thresholds
H1–H6 / S1–S5 and the artifact identity contract) is in place; acceptance
rows 1–2 and 4–7 and 10 carry fresh machine evidence at the soak head, row 3
(sustained duration) and row 8 (exact-RC soak) are the externally blocked
pair, and row 9 findings are documented in-lane (F1–F12 with
earliest-broken-invariant mapping; GitHub filing prohibited in this lane).

Progress: checked 1 issue; done 0 acceptance-complete issues (8/10 rows
evidenced fresh and re-verified, 2 externally blocked); skipped 0; validation
errors 0; escalated 1 (RC designation under parent #89); inventory delta 0.
