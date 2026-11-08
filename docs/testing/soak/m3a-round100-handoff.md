# Issue #860 — round 100 (job 7abe90ee) repair at ed0fe24a0: soak evidence refreshed onto the develop-merge head

**Not promotion evidence or integration approval.** Two things changed since
round 99's validation at `7f845e992` (an ancestor of this round's head), and
this round addresses both by execution rather than argument:

1. **The stale driver failure is re-confirmed stale at this head.** This job
   directory contains no `check-*.log` files (verified by listing); the
   referenced failure is the historical `98a11313/check-3.log`
   (`test_ensure_schema_fences_ddl_behind_advisory_lock`, `assert 24 == 21`
   at verify head `872fd2cea`). Re-executed at this round's head: green.
2. **The develop merge expired the soak evidence's production-code binding.**
   HEAD `ed0fe24a07a008f2ca9e2d092d8140370ab10aad` is the merge of `develop`
   `3c761d14db944a727fa0744444bc67cfe36d49f7` into `auto-860`, and
   `git diff --name-only 7f845e992..HEAD -- packages/ scripts/ tests/` is
   non-empty over production source: `maistro/container.py`,
   `extensions/{__init__,compatibility,health,service,sqlite_health_store,store}.py`,
   `runs/pg_store.py`, `_vulture_whitelist.py`, and
   `maistro_server/api/extensions.py`. Round-44's "production-code identity
   unchanged from the soak head `b4cfb94db`" claim therefore does not carry to
   this head, so the full soak harness was re-run on the new identity.

## Deterministic battery at `ed0fe24a0` (all green, re-executed this round)

| Gate | Result |
| --- | --- |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -q` | **38 passed, 6 skipped** — the `98a11313/check-3.log` failure does not reproduce (fence fix `cd77bb81c` is an ancestor) |
| `uv run ruff check .` / `uv run ruff format --check .` | All checks passed / 3,277 files already formatted |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_gitleaksignore_contract.py tests/test_prod_stack_boot_contract.py -q` | **81 passed** |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (CI's exact arguments) | rc=0: **1,323 reviewed identities → 1,323 findings**, `unclassified: 0`, `never_allowlist: 0` (base `3c761d14db94`, candidate `ed0fe24a07a0`) — the develop-side modules were already banked; no ledger amendment |
| `uv run python scripts/check-radon-baseline.py` | **137 reviewed C-or-worse blocks → 137** |
| `uv run python scripts/check-suite-inventory.py` | ok: **17/17 suites** (31,205 unique identities; delta 0, no tests added) |
| `uv run python scripts/check-backlog-consistency.py` | OK: 168 items |
| `scripts/check-shipped-surface-truth.py` / `check-promotion-surface.py` / `check-release-consistency.py` / `check-merge-markers.py` / `check-doc-links.py` / `git diff --check` | Matrix complete / ok / released none, shipping 0.9.0, working toward 1.0.0 / no conflict markers / 0 broken links / clean |

## Fresh soak executed at `ed0fe24a0` (round-100 evidence pack)

Exact round-44 invocation, fresh-db, on the dedicated soak Postgres
(`pgvector/pgvector:pg18`, digest in `hashes.postgres_image`); 02:27:09→
02:36:35 UTC; artifacts `evidence/m3a-round100-shakedown.json` (+ `-lb.log`,
`-nginx-soak-rendered.conf`), bound to `git_head ed0fe24a0…` with
**`git_clean=true`** (out-dir was a git-ignored scratch path at run time; the
three artifacts were copied into the tracked evidence directory afterwards).

- 55,289 requests through the LB (`health_ready` 29,681, `health_live`
  13,076, `run_get` 6,497, `task_submit` 2,692, `metrics_unauth` 3,343);
  sustained-phase statuses 200×42,757, 202×2,692, 401×3,343, 404×6,497 —
  **no 5xx outside the drain window**.
- Exactly-once task admission: 12 concurrent duplicate-`Idempotency-Key`
  submissions → 12 × 202 → **1 distinct run id** (`ce8730ee…`,
  `duplicate_run_ids: 11`).
- Exactly-once schedule occurrence (two OS processes racing
  `ScheduleRunAdmitter.admit_due` on the canonical store):
  **0 occurrences with multiple runs**; probe run terminalized (`cancelled`).
- Rate limiting: all six probe paths (LB × auth/unauth, direct replica ×
  auth/unauth) burst to 429 with `Retry-After` + `x-ratelimit-*` headers
  (600/800, 600/800, 504–538/800, 411–428/800 shapes); process-local
  per-replica scope unchanged and regression-locked by
  `test_replica_selection_has_an_independent_production_allowance`.
- Kill/restart: SIGTERM at 02:29:44 → drain exited after **1.5 s** with
  **0 5xx / 0 conn errors**, no escalation; replica_2 rejoined (window 9.02 s,
  0 LB errors vs the 4,320-error passive-health budget).
- Stability: admission-availability ratio **1.0** (2,640/2,640 outside the
  kill window, 0 unretryable 429s); RSS +8.7 % / +6.8 %; FDs 30→37 (max 40) /
  29→35 (max 39); **0 nonterminal runs** after settle (2,693 `completed`,
  1 probe `cancelled`).
- `failed_promotion_checks()` loaded live from `scripts/soak/run_soak.py` at
  this head, applied to the round-100 pack → exactly
  `['sustain_duration', 'exact_rc_artifact']`; the same replay against the
  committed round-44 pack returns the identical pair. All eight functional
  gates carry fresh numeric evidence on the new production-code identity;
  the merged extensions/health subsystem booted, served, drained, and
  recovered inside the soak with no new failure mode.

## Terminal blockers unchanged and external (same framing as round 99)

The two remaining acceptance rows stay outside any in-lane round's reach:
`sustain_duration` requires ≥ 14,400 s — above the 5,400 s lane timeout, with
background execution prohibited — and `exact_rc_artifact` refuses
host-preflight topology by design (`run_soak.py:67` floor;
`preflight_artifact_check` refusal, deliberately no CLI override). No RC designation exists:
parent #89 is open with the RC built "only from the candidate commit"
requirement, linked PRs #1567/#1602 are closed and #1672 is an open draft.
This remains an escalation to the release owner under parent #89 (RC freeze,
production Compose runner, ≥ 4 h soak window, provider keys, rate-limit
ownership decision), not a code or gate defect.

Progress: checked 1 issue; done 0 acceptance-complete issues (8/10 rows
evidenced fresh at `ed0fe24a0`, 2 externally blocked); skipped 0;
validation errors 0; escalated 1 (RC designation under parent #89); inventory
delta 0 (no test nodes added or removed; suite-inventory gate green).
