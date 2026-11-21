# Issue #860 — round 108 (job 35bce8d9) fresh soak execution and battery at c39ff2d51

**Not promotion evidence or integration approval.** The previous job on this
lane at this exact head (`243b259b`, head `c39ff2d51aef`) died on a provider
timeout (`Request timed out`, `failure_kind: provider_error`) after executing
zero checks — its job directory contains no `check-*.log`. Round 107 (job
`6b2c7d51`) had re-run the soak + battery at `0321df23a`, one docs commit
below this head. This round closes the gap the same way round 107 did: fresh
execution at the current head. `git diff 0321df23a..c39ff2d51` touches only
`docs/testing/soak/` (round-107 evidence + handoff); `git diff --name-only
0321df23a..c39ff2d51 -- packages/ scripts/ quality/` is empty, so the
production identity is unchanged — and this round re-proves it by execution
rather than by diff argument alone. No source, test, or ledger change was
identified or made.

## Snapshot

- Head `c39ff2d51aefaca7ef4de945a20e5264840fcf54` (round-107 lineage, one
  docs commit over round-107's soak-bound `0321df23a`). Tree clean at start
  and at soak run time (`git_clean=true`,
  `git_status_sha256=e3b0c442…` empty-tree sha, recorded in the evidence).
- The dispatch job directory contained **no `check-*.log` files** (driver ran
  zero deterministic checks — provider timeout). Every result below was run
  fresh in this round and logged as `check-*.log` in the job directory
  `/home/dev/maistro/jobs/35bce8d963a4448ea303adbad36eb169/`.

## Deterministic battery at `c39ff2d51` (all green, this round)

| Gate | Result |
| --- | --- |
| `uv sync --locked --extra dev` | ok (check-0) |
| `uv run ruff check .` | All checks passed (check-1) |
| `uv run ruff format --check .` | 3,301 files already formatted (check-2) |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (quality.yml CI-exact arguments) | rc=0: **1,322 reviewed identities → 1,322 findings**, `unclassified: 0`, `never_allowlist: 0` (base `321cbdb8fe9b`, candidate `c39ff2d51aef`) — no ledger amendment (check-3) |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_gitleaksignore_contract.py tests/test_prod_stack_boot_contract.py -q` | **89 passed** (check-4) |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -q` | **37 passed, 6 skipped** — the historical `98a11313/check-3.log` failure (`test_ensure_schema_fences_ddl_behind_advisory_lock`, `assert 24 == 21` at head `872fd2ceae8a`) does not reproduce on this lineage; skips require `MAISTRO_TEST_PG_DSN` (check-5) |
| `uv run mypy` (ci.yml ten package srcs) | **Success: no issues found in 1057 source files** (check-6) |
| `uv run python scripts/check-suite-inventory.py` | ok: **17/17 suites** match the recorded inventory (check-7) |

## Fresh soak executed at `c39ff2d51` (round-108 evidence pack)

Round-26/43/100/107 documented invocation, fresh-db (default), on the
dedicated soak Postgres (`pgvector/pgvector:pg18`, digest `2358fcba…`);
04:42:52→04:52:16 UTC (9m24s); scratch out-dir `/tmp/soak-round108` kept
`git_clean=true` at run time; the three artifacts were copied into the tracked
evidence directory afterwards as `evidence/m3a-round108-shakedown.json` (+
`-lb.log`, `-nginx-soak-rendered.conf`), bound to
`hashes.git_head = c39ff2d51…`; the rendered nginx conf on disk sha256-matches
`hashes.nginx_rendered_conf_sha256 = 86291c53…`.

- 2× `maistro_server` replicas on 18201/18202 booted via the RC entrypoint
  path in **2.6 s** behind the nginx LB on 18080; 420.08 s sustained mix.
- Exactly-once task admission: 12 concurrent duplicate-`Idempotency-Key`
  submissions → 12×202 → **1 distinct run id**, `duplicate_run_ids: 11`,
  `runs_sharing_one_task_run_identity: 0`.
- Exactly-once schedule occurrence (two OS processes racing
  `ScheduleRunAdmitter.admit_due` on the canonical store): **0 occurrences
  with multiple runs**; probe run terminalized (`cancelled`).
- Kill/restart: SIGTERM at 04:45:26 → drain exited after **1.0 s** with
  **0 5xx / 0 conn errors**, no escalation (rc 143); replica_2 rejoined in
  **5.1 s**; kill window (6.09 s) status mix 200×677, 202×26, 401×52, 404×48,
  0×"no request" — `lb_failover_bounded` ok (**0 observed errors vs 4,320
  passive-health budget**, 27.0 s upper-bound kill window); `lb.log` contains
  no 5xx lines.
- Stability: admission-availability ratio **1.0** (2,770/2,770 task
  submissions outside the kill window, 0 unretryable 429s); RSS +8.9 % /
  +7.5 %; FDs 30→35 (max 40) / 29→35 (max 38); **0 nonterminal runs** after
  settle (2,797 `completed`, 1 probe `cancelled`).
- Rate limiting: all six probe paths (LB × auth/unauth, direct replica ×
  auth/unauth) burst to 429 with `Retry-After` + `x-ratelimit-*` headers
  (`enforced_everywhere=true`, probe 800 > burst 100); per-replica
  allowed-counts again differ (200 vs 224 authenticated direct) —
  process-local per-replica scope (`enforcement_scope: "process-local;
  aggregate budget is replica count times limit"`) unchanged, regression-locked
  by `test_replica_selection_has_an_independent_production_allowance`
  (tests/test_soak_promotion_gates.py:439). **This is contrary evidence for
  acceptance row 5** (cluster budget not enforceable via replica selection
  with `InMemoryRateLimiter`), same product fact as rounds 100/106/107.
- Promotion gates loaded live from `scripts/soak/run_soak.py` at this head and
  applied to the fresh pack by the driver itself → exit 1 with exactly
  **`['sustain_duration', 'exact_rc_artifact']`** (check-8-soak.log); all
  functional checks green.
- Teardown verified: no orphan soak uvicorn/nginx processes, ports
  18080/18201/18202 free; only the dedicated `maistro-soak-pg` container
  remains.

## What this does and does not change

The fresh pack re-evidences the **functional** rows (1 profile-defined mix,
2 two-replica exercise, 4 exactly-once admission, 6 telemetry with
thresholds, 7 kill/restart drain/fencing/recovery, 10 machine+human-readable
hash-bound evidence) **on the current production identity** — the same
disposition round 107 reached for its head, now re-proven one docs commit
later. It does **not** change the promotion disposition:

- `sustain_duration` (row 3) still requires ≥ 14,400 s
  (`run_soak.py:69` `PROMOTION_MIN_SUSTAIN_SECONDS`) — above any in-lane
  round window, background execution prohibited.
- `exact_rc_artifact` (row 8) still refuses host-preflight topology by design
  (`run_soak.py` threshold: "not the exact production Compose image and
  configuration"): no RC exists to soak — parent **#89 open**, RC PR **#1672
  open draft**; #1567/#1602/#2100 are merged history, none a designation.
- Row 5 remains **contrary**: the per-replica independent allowance is a
  product property (process-local `InMemoryRateLimiter`,
  `packages/maistro-server/src/maistro_server/api/rate_limit.py`),
  re-observed under load, not fixable by soak evidence.
- Any soak at the eventual promotion commit remains required: this run binds
  `c39ff2d51`, not whatever commit #89 ultimately promotes.

## Disposition

Acceptance rows 3 and 8 remain **externally blocked** (RC designation under
the open parent #89, production Compose runner, ≥ 4 h soak window); row 5
carries contrary product evidence; rows 1-2, 4, 6-7 and 10 carry fresh
bounded evidence at this head but must be re-evidenced at the eventual
promotion commit. Filing findings on GitHub is prohibited in this lane; the
F1-F12 mapping to earliest broken invariants stays in-repo. Escalation to the
release owner is unchanged.

Progress: checked 1 issue; done 0 acceptance-complete issues (rows 3, 5, 8
blocked or contrary); skipped 0; validation errors 0; escalated 1 (RC
designation under parent #89); inventory delta 0 (no tests added or removed;
17/17 suites unchanged); repairs 0 (battery fully green — nothing to repair).
