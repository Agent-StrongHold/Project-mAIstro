# Issue #860 — round 109 (job 30ae0fec) develop-base sync + fresh battery and soak at merged head

**Not promotion evidence or integration approval.** Round 108 closed BLOCKED on
the two external promotion gates (≥ 14,400 s sustain; no exact-RC artifact to
soak). This round resolves the one evidenced in-lane defect that remained:
the branch did not contain its declared develop base `ab8b3737f` —
`HEAD..origin/develop` was 3 commits (`4c1e93936` dependabot
`actions/upload-artifact` 6→7, `ac7370141` dependabot `actions/setup-node`
6→7, `ab8b3737f` #1627 beam-selection assertions + multi-line `run_graph`
import-scan tests). `git merge-tree` over the true merge base `321cbdb8fe9b`
showed zero conflicts and zero both-changed files, so the merge was executed
and committed as **`5a59c724a`** (merge commit; every conflict-free). No
source, test, or ledger file was authored by this lane; the only tree content
added after the merge is this round's evidence + handoff.

## Snapshot

- Start head `fa0ae8291` (round-108 lineage), tree clean. End head
  `5a59c724a20ef1241d57c048df90758f2c2e1e25` (merge + evidence commit).
- The dispatch job directory contained **no `check-*.log` files**: the driver
  executed zero deterministic checks this round. Every result below was run
  fresh in this round and logged as `check-*.log` in the job directory
  `/home/dev/maistro/jobs/30ae0fec255e464bb1beabf41b37e44d/`.
- Inventory: develop's `ab8b3737f` ships its own delta note
  (`chore-run-graph-retirement-review-followups-0475.md`, +4 `tests/`), so the
  delta ledger absorbs the merge — **no new inventory note needed, no test
  added or removed by this lane**; `tests/` went 5,287 → 5,291 collected
  (31,323 → 31,327 total node IDs).

## Deterministic battery at `5a59c724a` (all green, this round)

| Gate | Result |
| --- | --- |
| `uv sync --locked --extra dev` | ok (check-0) |
| `uv run ruff check .` | All checks passed (check-1) |
| `uv run ruff format --check .` | 3,301 files already formatted (check-2) |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (quality.yml CI-exact arguments) | rc=0: **1,322 reviewed identities → 1,322 findings**, `unclassified: 0`, `never_allowlist: 0` — ratchet now reads base `ab8b3737fa64` (the restored develop base), candidate `5a59c724a20e`; no ledger amendment (check-3) |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_gitleaksignore_contract.py tests/test_prod_stack_boot_contract.py -q` | **89 passed** (check-4) |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -q` | **37 passed, 6 skipped** (skips need `MAISTRO_TEST_PG_DSN`) (check-5) |
| `uv run mypy` (ci.yml ten package srcs) | **Success: no issues found in 1057 source files** (check-6) |
| `uv run python scripts/check-suite-inventory.py` | ok: **17/17 suites** match the recorded inventory, 31,327 collected node IDs, 0 duplicate/byte-identical evidence (check-7) |

## Fresh soak executed at `5a59c724a` (round-109 evidence pack)

Round-26/43/100/107/108 documented invocation, fresh-db (default), on the
dedicated soak Postgres (`pgvector/pgvector:pg18`); 05:17:26→05:26:50 UTC
(9m24s); scratch out-dir `/tmp/soak-round109` kept `git_clean=true` at run
time (evidence records `git_clean=true`,
`git_status_sha256=e3b0c442…` empty-tree sha, `git_head=5a59c724a…`); the
three artifacts were copied into the tracked evidence directory afterwards as
`evidence/m3a-round109-shakedown.json` (+ `-lb.log`,
`-nginx-soak-rendered.conf`); the rendered nginx conf on disk sha256-matches
`hashes.nginx_rendered_conf_sha256 = 86291c53…` (verified post-copy).

- 2× `maistro_server` replicas on 18201/18202 booted via the RC entrypoint
  path in **2.5 s** behind the nginx LB on 18080; **420.05 s** sustained mix.
- Exactly-once task admission: 12 concurrent duplicate-`Idempotency-Key`
  submissions → 12×202 → **1 distinct run id**, `duplicate_run_ids: 11`,
  `runs_sharing_one_task_run_identity: 0`.
- Exactly-once schedule occurrence (two OS processes racing
  `ScheduleRunAdmitter.admit_due` on the canonical store): **0 occurrences
  with multiple runs**; probe run terminalized (`cancelled`).
- Kill/restart: SIGTERM at 05:20:00 → drain exited after **1.0 s** with
  **0 5xx / 0 conn errors**, no escalation (rc 143); replica_2 rejoined
  05:20:06.8 (**6.6 s** after the signal, 1.0 s of it draining) with
  `rejoined: true`; kill window 6.58 s status mix 200×735, 202×31,
  401×52, 404×60, 0×"no request" — `lb_failover_bounded` ok (**0 observed
  errors vs 4,320 passive-health budget**, 27.0 s upper-bound kill window);
  `lb.log` contains no 5xx lines.
- Stability: admission-availability ratio **1.0** (2,764/2,764 task
  submissions outside the kill window, 0 unretryable 429s); RSS +9.0 % /
  +7.7 %; FDs 30→36 (max 41) / 29→34 (max 39); metrics trace 212 samples;
  **0 nonterminal runs** after settle (2,796 `completed`, 1 probe
  `cancelled`).
- Rate limiting: all six probe paths (LB × auth/unauth, direct replica ×
  auth/unauth) burst to 429 with `Retry-After` + `x-ratelimit-*` headers
  (`enforced_everywhere=true`); per-replica allowed-counts again differ
  (200 vs 226 authenticated direct) — process-local per-replica scope
  (`enforcement_scope: "process-local; aggregate budget is replica count
  times limit"`) unchanged, regression-locked by
  `test_replica_selection_has_an_independent_production_allowance`
  (tests/test_soak_promotion_gates.py:439). **This is contrary evidence for
  acceptance row 5** (cluster budget not enforceable via replica selection
  with `InMemoryRateLimiter`), same product fact as rounds 100/106/107/108.
- Promotion gates loaded live from `scripts/soak/run_soak.py` at this head and
  applied to the fresh pack by the driver itself → exit 1 with exactly
  **`['sustain_duration', 'exact_rc_artifact']`** (check-8-soak.log); all
  functional checks green.
- Teardown verified: no orphan soak uvicorn/nginx processes, ports
  18080/18201/18202 free; only the dedicated `maistro-soak-pg` container
  remains.

## What this does and does not change

The develop-base merge restores the lane's declared base so future
integration starts from a contained diff, and the fresh pack re-evidences the
**functional** rows (1 profile-defined mix, 2 two-replica exercise, 4
exactly-once admission, 6 telemetry with thresholds, 7 kill/restart
drain/fencing/recovery, 10 machine+human-readable hash-bound evidence) on the
merged production identity. It does **not** change the promotion disposition:

- `sustain_duration` (row 3) still requires ≥ 14,400 s
  (`run_soak.py` `PROMOTION_MIN_SUSTAIN_SECONDS`, observed 420.05) — above any
  in-lane round window, background execution prohibited.
- `exact_rc_artifact` (row 8) still refuses host-preflight topology by design
  (`thresholds.checks.exact_rc_artifact.reason`: "not the exact production
  Compose image and configuration"): no RC exists to soak — parent **#89
  open**, RC PR **#1672 open draft**; #1567/#1602/#2100 are merged history,
  none a designation.
- Row 5 remains **contrary**: the per-replica independent allowance is a
  product property (process-local `InMemoryRateLimiter`,
  `packages/maistro-server/src/maistro_server/api/rate_limit.py`),
  re-observed under load, not fixable by soak evidence.
- Any soak at the eventual promotion commit remains required: this run binds
  `5a59c724a`, not whatever commit #89 ultimately promotes.

## Disposition

Acceptance rows 3 and 8 remain **externally blocked** (RC designation under
the open parent #89, production Compose runner, ≥ 4 h soak window); row 5
carries contrary product evidence; rows 1-2, 4, 6-7 and 10 carry fresh
bounded evidence at the merged head but must be re-evidenced at the eventual
promotion commit. Filing findings on GitHub is prohibited in this lane; the
F1-F12 mapping to earliest broken invariants stays in-repo. Escalation to the
release owner is unchanged.

Progress: checked 1 issue; done 0 acceptance-complete issues (rows 3, 5, 8
blocked or contrary); skipped 0; validation errors 0; escalated 1 (RC
designation under parent #89); inventory delta 0 (develop's own delta note
absorbs the upstream +4 `tests/`; no tests added or removed by this lane);
repairs 1 (develop-base sync merged conflict-free as `5a59c724a`, battery +
soak re-proven at the merged head).
