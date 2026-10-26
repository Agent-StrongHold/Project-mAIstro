# Issue #860 — round 104 (job 789ce7ba) independent re-validation at b9901d49c

**Not promotion evidence or integration approval.** The previous block was
again "worker requested attention: NEEDS-DEEP-REVIEW" caused by a
provider-timeout job (`1bb0edee6a80`, `failure_kind: provider_error`,
`checks: []` — zero checks executed, then a second timeout). This round
resolves the block by re-executing the full deterministic battery at the
current head without taking any prior round's claims on trust. No repair was
needed; the only change is this note.

## Snapshot

- Head `b9901d49c3205b4b719c6f60998d51b730758700` (round-103 docs commit),
  tree clean before and after this note commit; base
  `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- `git diff --name-only 051eb0f22..HEAD` = round-103 handoff doc only, and
  `git diff --name-only ed0fe24a07a0..HEAD -- packages scripts tests deploy`
  is empty: production source is byte-identical to the soak head, so the
  round-100 evidence binding (`hashes.git_head = ed0fe24a0…`,
  `git_clean = true`) remains valid at this head.
- This job directory contains no `check-*.log` files; the historical
  validation failure remains `98a11313/check-3.log`
  (`test_ensure_schema_fences_ddl_behind_advisory_lock`, `assert 24 == 21`)
  at a verify head predating the F7 advisory-lock fix — re-executed below
  and it does not reproduce.

## Re-executed deterministic battery at `b9901d49c` (all green, this round)

| Gate | Result |
| --- | --- |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -q` | **38 passed, 6 skipped** — the `98a11313` failure does not reproduce at this head |
| `uv run ruff check .` / `uv run ruff format --check .` | All checks passed / 3,277 files already formatted |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_gitleaksignore_contract.py tests/test_prod_stack_boot_contract.py -q` | **81 passed** |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (CI's exact arguments) | rc=0: **1,323 reviewed identities → 1,323 findings** (base `3c761d14db94`, candidate `b9901d49c320`) — no ledger amendment |
| `uv run python scripts/check-radon-baseline.py` | rc=0: **137 → 137** C-or-worse blocks |
| `uv run python scripts/check-suite-inventory.py` | ok: **17/17 suites** match the recorded inventory (delta 0 this round — docs-only change) |
| `uv run python scripts/check-backlog-consistency.py` | OK: 168 items |
| `check-shipped-surface-truth.py` / `check-promotion-surface.py` / `check-release-consistency.py` / `check-merge-markers.py` / `check-doc-links.py` / `check_enumerations.py` / `check-workspace-retirement.py` / `bump_version.py --check` | Matrix complete / ok / released none, shipping 0.9.0 / no conflict markers / 0 broken links / no new enumeration gaps / 89 ledger entries match the tree / 42 sites agree on 0.9.0 |

## Round-100 evidence pack re-verified from the harness code, not the prose

`failed_promotion_checks()` was imported from `scripts/soak/run_soak.py` at
this head and applied to the committed packs:

- `evidence/m3a-round100-shakedown.json` → exactly
  **`['sustain_duration', 'exact_rc_artifact']`** (observed sustain
  420.04 s vs `PROMOTION_MIN_SUSTAIN_SECONDS = 14_400`).
- `evidence/m3a-round44-shakedown.json` → the identical failing pair.

Pack contents re-read from raw JSON this round: `exactly_once_tasks` —
12 concurrent duplicate-`Idempotency-Key` submissions → 12 × 202 → exactly 1
distinct run id (`ce8730ee…`, `duplicate_run_ids: 11`, `cause: ok`);
`exactly_once_schedule_claim.occurrences_with_multiple_runs = 0`;
`rate_limit` — six-path probe (`direct_replicas` × auth/unauth + LB auth +
LB unauth), 16-way concurrent bursts of 800 requests, 429 majority with
`x-ratelimit-*`/`Retry-After` headers, `enforced_everywhere: true`, and
`enforcement_scope` honestly records "process-local; aggregate budget is
replica count times limit" (the #842 cluster-budget question stays open, not
silently passed); `kill_restart` — SIGTERM, `drained: true` in 1.5 s,
`drain_5xx: 0`, `drain_conn_errors: 0`, `escalated: false`, `rejoined:
true`; `nonterminal_runs_after_settle.count = 0`;
`task_admission_availability` ratio 1.0 (2,640/2,640 accepted outside the
kill window, 0 unretryable 429s); `hashes.postgres_image` pinned by digest;
`git_clean: true` at the soak head.

## Observations (not repairs)

- `git diff --check 3c761d14..HEAD` flags whitespace in **historical
  committed docs** (`m3a-round88-handoff.md:62`, the `issue-860-*-repair`
  notes). No workflow references `git diff --check` (verified by grep over
  `.github/workflows/`), each individual commit is clean per
  `git show --check`, and rewriting committed historical evidence for
  cosmetics would violate the evidence-preservation stance. Recorded here so
  the artifacts are visible; no gate is affected.
- F7 (concurrent `CREATE INDEX IF NOT EXISTS` boot race) remains fixed in
  production: `_SCHEMA_LOCK_KEY = 0x6D61_656C` ("mael") advisory lock taken
  before the DDL body (`packages/maistro-core/src/maistro/persistence/
  pg_learnings.py:177,216`), fenced by the repaired test.

## Terminal blockers unchanged and external — verified by construction

- **`sustain_duration`**: `PROMOTION_MIN_SUSTAIN_SECONDS = 14_400`
  (`scripts/soak/run_soak.py:67`) vs the 5,400 s lane timeout, with
  background execution prohibited. Not reachable from any in-lane round.
- **`exact_rc_artifact`**: `preflight_artifact_check()`
  (`scripts/soak/run_soak.py:730`) returns `ok: false` for the
  host-uvicorn-preflight topology with "deliberately no CLI override". No RC
  designation exists: parent #89 is open, #1567/#1602 are closed and #1672
  is an open draft.

Escalation to the release owner under parent #89 is unchanged (RC freeze,
production Compose runner, ≥ 4 h soak window, provider keys, rate-limit
ownership decision). Acceptance rows 1–2 and 4–7 and 10 carry fresh,
re-verified machine evidence at the soak head; row 3 (sustained duration)
and row 8 (exact-RC soak) remain the externally blocked pair; row 9 findings
are documented in-lane (F1–F12 with earliest-broken-invariant mapping;
GitHub filing prohibited in this lane).

Progress: checked 1 issue; done 0 acceptance-complete issues (8/10 rows
evidenced fresh and re-verified, 2 externally blocked); skipped 0; validation
errors 0; escalated 1 (RC designation under parent #89); inventory delta 0.
