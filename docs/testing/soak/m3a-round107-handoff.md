# Issue #860 — round 107 (job 6b2c7d51) fresh soak execution at 0321df23a

**Not promotion evidence or integration approval.** Round 106 (job
`a1929c49`) closed with "worker requested attention: BLOCKED"; the block was
not a develop sync conflict (the only two commits on `origin/develop` not in
this branch are `.github/workflows` dependabot bumps `4c1e93936`/`ac7370141`,
touched by no production path). The one evidenced action available in-lane had
not been taken since the production drift: rounds 101-106 were prose-only
re-validations, while the round-100 soak pack stayed hash-bound to
`ed0fe24a07a0` — 39 production files behind. This round closes that gap by
execution: the bounded multi-replica soak was re-run fresh at the current
head, plus the full deterministic battery. No source, test, or ledger change
was identified or made.

## Snapshot

- Head `0321df23affd5f4923cb61d1839ab00f4e0fa7ac` (round-106 handoff lineage,
  one docs commit over round-106's validated `b2b367b429`; production
  identity identical to round 106's validated tree). Tree clean at start.
- This job directory contained **no `check-*.log` files**: the driver executed
  zero deterministic checks this round. Every result below was run fresh in
  this round and logged as `check-*.log` in the job directory.
- Environment note: `uv sync --locked --extra dev` re-confirmed ("Checked 214
  packages"); `maistro_server` is intentionally not an installed root
  dependency — pytest's `pythonpath` (pyproject.toml:294-301) supplies it, so
  the bare `import maistro_server` probe failing is expected, not a defect.

## Deterministic battery at `0321df23a` (all green, this round)

| Gate | Result |
| --- | --- |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3,301 files already formatted |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (quality.yml:1079-1082 exact arguments) | rc=0: **1,322 reviewed identities → 1,322 findings**, `unclassified: 0`, `never_allowlist: 0` (base `321cbdb8fe9b`, candidate `0321df23affd`) — no ledger amendment |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_gitleaksignore_contract.py tests/test_prod_stack_boot_contract.py -q` | **89 passed** |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -q` | **37 passed, 6 skipped** — the historical `98a11313/check-3.log` failure (`assert 24 == 21`) still does not reproduce; skips require `MAISTRO_TEST_PG_DSN` |
| `uv run mypy` (ci.yml:117-127's ten package srcs) | **Success: no issues found in 1057 source files** |
| `uv run python scripts/check-suite-inventory.py` | ok: **17/17 suites** match the recorded inventory |

## Fresh soak executed at `0321df23a` (round-107 evidence pack)

Round-26/43/100 documented invocation, fresh-db, on the dedicated soak
Postgres (`pgvector/pgvector:pg18`); 04:07:34→04:17:00 UTC (9m27s); scratch
out-dir `/tmp/soak-round107` kept `git_clean=true` at run time; the three
artifacts were copied into the tracked evidence directory afterwards as
`evidence/m3a-round107-shakedown.json` (+ `-lb.log`,
`-nginx-soak-rendered.conf`), bound to `hashes.git_head = 0321df23a…`,
`git_clean=true`, `git_status_sha256 = e3b0c442…` (empty-tree sha).

- 2× `maistro_server` replicas on 18201/18202 booted via the RC entrypoint
  path in **2.6 s** behind the nginx LB on 18080; 420.07 s sustained mix.
- Sustained-phase statuses **200×47,537, 202×2,804, 401×3,445, 404×3,457**
  plus one `0` (receipt-pending `run_get` "no request" record,
  `run_soak.py:876-880`), ~57.2k requests total — **no 5xx anywhere, drain
  window included**.
- Exactly-once task admission: 12 concurrent duplicate-`Idempotency-Key`
  submissions → 12×202 → **1 distinct run id** (`328b644d…`,
  `duplicate_run_ids: 11`); 0 runs sharing one task run identity.
- Exactly-once schedule occurrence (two OS processes racing
  `ScheduleRunAdmitter.admit_due` on the canonical store): **0 occurrences
  with multiple runs**; probe run terminalized (`cancelled`).
- Kill/restart: SIGTERM at 04:10:10 → drain exited after **1.0 s** with
  **0 5xx / 0 conn errors**, no escalation (rc 143); replica_2 rejoined in
  **6.59 s** with 0 LB errors vs the 4,320-error passive-health budget.
- Stability: admission-availability ratio **1.0** (2,774/2,774 outside the
  kill window, 0 unretryable 429s); RSS +8.9 % / +7.7 %; FDs 30→34 (max 41) /
  29→36 (max 39); **0 nonterminal runs** after settle (2,805 `completed`,
  1 probe `cancelled`).
- Rate limiting: all six probe paths (LB × auth/unauth, direct replica ×
  auth/unauth) burst to 429 with `Retry-After` + `x-ratelimit-*` headers
  (`enforced_everywhere=true`); per-replica allowed-counts again differ
  (200 vs 205 authenticated direct) — process-local per-replica scope
  unchanged, regression-locked by
  `test_replica_selection_has_an_independent_production_allowance`
  (tests/test_soak_promotion_gates.py:439). **This is contrary evidence for
  acceptance row 5** (cluster budget not enforceable via replica selection
  with `InMemoryRateLimiter`), same product fact as rounds 100/106.
- `failed_promotion_checks()` loaded live from `scripts/soak/run_soak.py` at
  this head, applied to the fresh pack → exactly
  **`['sustain_duration', 'exact_rc_artifact']`** (run exit 1, expected);
  the same replay on the committed round-100 pack returns the identical pair.
- Teardown verified: no orphan uvicorn/nginx processes, ports 18080/18201/
  18202 free; only the dedicated `maistro-soak-pg` container remains.

## What this does and does not change

The fresh pack re-evidences the **functional** rows (1 profile-defined mix,
2 two-replica exercise, 4 exactly-once admission, 6 telemetry with
thresholds, 7 kill/restart drain/fencing/recovery, 10 machine+human-readable
hash-bound evidence) **on the current production identity** — closing the
round-106 staleness finding for the preflight tier. It does **not** change
the promotion disposition:

- `sustain_duration` (row 3) still requires ≥ 14,400 s
  (`run_soak.py:67` `PROMOTION_MIN_SUSTAIN_SECONDS`) — above any in-lane
  round window, background execution prohibited.
- `exact_rc_artifact` (row 8) still refuses host-preflight topology by
  design (`run_soak.py:744-756`): no RC exists to soak — parent **#89 open**,
  RC PR **#1672 open draft**; #1567/#1602/#2100 are merged history, none a
  designation.
- Row 5 remains **contrary**: the per-replica independent allowance is a
  product property (process-local `InMemoryRateLimiter`,
  `packages/maistro-server/src/maistro_server/api/rate_limit.py`),
  re-observed under load, not fixable by soak evidence.
- Any soak at the eventual promotion commit remains required: this run
  binds `0321df23a`, not whatever commit #89 ultimately promotes.

## Disposition

Acceptance rows 3 and 8 remain **externally blocked** (RC designation under
the open parent #89, production Compose runner, ≥ 4 h soak window); row 5
carries contrary product evidence; rows 1-2, 4, 6-7 and 10 now carry fresh
bounded evidence at this head but must be re-evidenced at the eventual
promotion commit. Filing findings on GitHub is prohibited in this lane; the
F1-F12 mapping to earliest broken invariants stays in-repo. Escalation to the
release owner is unchanged.

Progress: checked 1 issue; done 0 acceptance-complete issues (rows 3, 5, 8
blocked or contrary); skipped 0; validation errors 0; escalated 1 (RC
designation under parent #89); inventory delta 0 (no tests added or removed;
17/17 suites unchanged); repairs 0 (battery fully green — nothing to repair).
