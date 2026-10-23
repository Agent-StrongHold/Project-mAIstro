# Issue #860 validation — job 5ce2d6d6

## Frozen scope

Only issue #860, branch `auto-860`, starting HEAD
`6bdcc1be48e233c621dcb3891663f2a181406f35`, develop base
`3c761d14db944a727fa0744444bc67cfe36d49f7`. Worktree clean at start; no
salvage needed; no remote mutations. Prior round resolved job 80201704's
`NEEDS-DEEP-REVIEW` as a verified ownership handoff; this round
independently re-verifies that resolution per the "do not assume earlier
verification claims are true" mandate.

Driver checks: this job directory contains no `check-*.log` files (verified
by listing). The referenced failure log is the historical
`98a113…/check-3.log` (`test_ensure_schema_fences_ddl_behind_advisory_lock`,
DDL count 24 vs 21); re-executed below rather than trusted.

## Executed checks on HEAD `6bdcc1be4` (all re-run this round, none trusted)

| Command | Result |
| --- | --- |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -q` | **37 passed, 6 skipped** — the check-3.log failure is stale on HEAD (fence fix landed in `cd77bb81c`) |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_gitleaksignore_contract.py tests/test_prod_stack_boot_contract.py -q` | **81 passed** |
| `uv run ruff check .` / `uv run ruff format --check .` | All checks passed / 3270 files already formatted |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | rc=0: 1323 reviewed identities → 1323 findings, `unclassified: 0`, `never_allowlist: 0`; ledger unamended (not a CI-repair round) |
| `uv run python scripts/check-suite-inventory.py` | `ok: 17 suite(s) match the recorded inventory` |
| `uv run python scripts/check-test-duplicates.py` | ok, 0 byte-identical groups |
| `uv run python scripts/check-backlog-consistency.py` | OK: 168 items, all statuses/citations resolve |
| `failed_promotion_checks(m3a-round44-shakedown.json)` (executed via `run_soak.py` import) | `['sustain_duration', 'exact_rc_artifact']` — exactly the two by-design host-preflight gates |

## Round-44 evidence audit (direct artifact reads + authoritative gate execution)

- `thresholds.checks` at HEAD: `exactly_once_task_admission`,
  `exactly_once_schedule_occurrence`, `rate_limit_enforced`,
  `replica_2_rejoined` all `true`; `graceful_drain` SIGTERM drained 1.0 s,
  0 5xx, 0 conn errors, no escalation, `ok: true`;
  `lb_failover_bounded` 0 observed vs budget 4320; `nonterminal_runs_after_settle`
  count 0; `task_admission_availability` ratio 1.0 (2296/2296);
  RSS growth +7.6 %/+7.2 %, FD max 47/42.
- Identity binding: `hashes.git_head = b4cfb94db…`, digest-pinned Postgres
  image, rendered-nginx/soak-env sha256 present; `git_clean=false` is honest
  (evidence out-dir untracked at run time; `git_diff_sha256` is the
  empty-string hash). `git diff --name-only b4cfb94db..HEAD` over non-docs
  paths is **empty** — production-code identity is unchanged from the soak
  head, so the round-44 pack remains the freshest valid evidence; re-running
  the 420 s soak for a docs-only delta adds no information.
- Live observations verified in the raw JSON: 12 concurrent duplicate
  `Idempotency-Key` submissions → 12 delivered, 1 distinct `run_id`; cross-
  process schedule-occurrence race → 0 occurrences with multiple runs,
  probe Run terminalized (`cancelled`); six-path rate-limit probes all 429
  with `Retry-After` + `x-ratelimit-*`.

## Code claims re-verified at source

- `packages/maistro-server/src/maistro_server/api/rate_limit.py`:
  enforcement-scope paragraph states process-local state, aggregate
  N × configured limit, "deliberately NOT advertised as cluster-wide" —
  the H3 standing contrary evidence, regression-locked by
  `test_replica_selection_has_an_independent_production_allowance`
  (`tests/test_soak_promotion_gates.py`, passed this round).
  `BACKLOG.md:267` engine-116 (Accepted; gap-spec; v1.0) tracks the
  cluster-wide budget; #842 is CLOSED (identity-keyed limits, verified in
  the dispatch snapshot).
- `scripts/soak/run_soak.py:730-741`: `preflight_artifact_check()` hard-fails
  host topology with no CLI override — correct by design;
  `PROMOTION_MIN_SUSTAIN_SECONDS = 14_400` is a module constant.
- `packages/maistro-server/src/maistro_server/main.py:648` installs
  `RateLimitMiddleware` per app/process.

## Acceptance audit (unchanged in substance, now re-confirmed on this HEAD)

Criteria proven in-lane on fresh HEAD-pinned evidence: ≥ 2 replicas under
mixed load, exactly-once task admission and schedule-occurrence claims,
rate-limit enforcement under concurrency (LB + both replicas + both
identity classes), kill/restart graceful drain + rejoin + bounded 5xx,
settle-to-zero nonterminal runs, bounded RSS/FD, machine- + human-readable
hash-tied evidence, load profile with explicit thresholds, findings filed
locally to their earliest invariants (F1–F12, engine-116; remote filing
prohibited in this lane).

Remaining outside worker authority (unchanged, precisely enumerated):

1. ≥ 4 h soak of the **exact RC Compose artifact** — `sustain_duration`
   (420.05 s vs 14 400 s) and `exact_rc_artifact` (host-uvicorn-preflight)
   are the only two failing gates and fail by construction; the parent
   #89 ("M3-A7 — Run RC soak and byte-equivalent final promotion", open)
   owns the candidate identity and the promotion run.
2. Cluster-wide rate-limit budget (H3) — security-owner disposition per
   engine-116 (v1.0); #842's accepted scope explicitly excludes it.

## Inventory notes

No test files added or modified this round (validation + report only); suite
counts unchanged (81 root gate tests; 37+6 pg-learnings). No
`docs/testing/inventory-notes/` delta required.

## Disposition

**BLOCKED on external ownership, lane work complete.** Every check
executable inside this lane is green on the exact starting HEAD, the only
failing promotion gates fail by design for a host preflight, and the deep
review (c5ac7039) adjudicated all prior findings CONFIRMED with no
in-tree repair remaining. The two remaining acceptance items are release-
owner (#89) and security-owner (engine-116) decisions. No code defect is
known to remain in this lane.
