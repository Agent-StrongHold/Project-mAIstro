# Issue #860 — round 112 (job 1274e121) validation of the round-111 state

**Not promotion evidence or integration approval.** The dispatched run chain
since round 111: job 8985af1cb died on a provider 429 before executing any
command (`result.json`: `failure_kind: rate_limited`, `checks: []`, zero
tree effect), and this round is the first re-execution at head `d530d64a6`.
This round re-proves the deterministic battery at the dispatched head,
resolves the standing verifier finding from job 98a11313 (check-3.log) as
**already fixed at the current head**, and re-confirms that the only open
acceptance rows remain externally blocked. No source, test, or ledger file
was authored or modified; the only tree content added is this record.

## Snapshot

- Start head `d530d64a6` — exactly the dispatched head; tree clean. End head:
  same + this record.
- The dispatch job directory contained **no `check-*.log` files**: the driver
  executed zero deterministic checks. Every result below was run fresh in
  this round and logged as `check-*.log` in
  `/home/dev/maistro/jobs/1274e1217df7473fb141ca5993eff286/`.
- `git fetch origin`: `origin/develop` is still `ab8b3737f` — the declared
  base, already an ancestor of HEAD. **No develop drift; no sync needed.**
- **Production identity binding intact**: `git diff 5a59c724a..d530d64a6
  --name-only` contains **zero non-`docs/` paths**, so the round-109 evidence
  pack (`hashes.git_head = 5a59c724a20e…`, `git_clean = true`) remains bound
  to the byte-identical production code at this head.

## Standing verifier finding resolved (job 98a11313, check-3.log)

That job's battery failed at
`packages/maistro-core/tests/persistence/test_pg_learnings.py::
test_ensure_schema_fences_ddl_behind_advisory_lock` (`assert 24 == 21` DDL
calls) — but at head `872fd2cea` against base `1e640df17`, i.e. **before** the
declared-base merge `5a59c724a` reconciled the fence test with develop's
schema body. Re-run fresh at the dispatched head:
**37 passed, 6 skipped** (check-5; skips require `MAISTRO_TEST_PG_DSN`). The
finding is closed by the merge, not by this round; nothing to repair.

## Deterministic battery at `d530d64a6` (all green, this round)

| Gate | Result |
| --- | --- |
| `uv sync --locked --extra dev` | ok (check-0) |
| `uv run ruff check .` | All checks passed (check-1) |
| `uv run ruff format --check .` | 3,301 files already formatted (check-2) |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (quality.yml CI-exact arguments) | rc=0: **1,322 reviewed identities → 1,322 findings**; base `ab8b3737fa64`, candidate `d530d64a64bd`; no ledger amendment (check-3) |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_gitleaksignore_contract.py tests/test_prod_stack_boot_contract.py -q` | **89 passed** (check-4), including the row-5 regression lock `test_replica_selection_has_an_independent_production_allowance` (tests/test_soak_promotion_gates.py:439) |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -q` | **37 passed, 6 skipped** (check-5) — job 98a11313's failing file, green at this head |
| `uv run mypy` with ci.yml's exact ten-package arguments | **Success: no issues found in 1057 source files** (check-6) |
| `uv run python scripts/check-suite-inventory.py` | ok: **17/17 suites** match the recorded inventory (check-7) |

## Promotion gates + evidence-pack integrity (check-8, reproduced live)

`PYTHONPATH=scripts` + `failed_promotion_checks` from `scripts/soak/run_soak.py`
applied to `docs/testing/soak/evidence/m3a-round109-shakedown.json` at this
head exits with exactly **`['sustain_duration', 'exact_rc_artifact']`** —
identical to rounds 109–111. All eight functional gates on the pack are
`ok=True` (`exactly_once_task_admission`, `exactly_once_schedule_occurrence`,
`rate_limit_enforced`, `lb_failover_bounded`, `replica_2_rejoined`,
`nonterminal_runs_after_settle`, `task_admission_availability`,
`graceful_drain`). Pack integrity re-verified live: rendered nginx conf on
disk sha256 `86291c53ab2a81fd…` **matches**
`hashes.nginx_rendered_conf_sha256`; `final_runs_by_status = completed=2796
cancelled=1`, `nonterminal_runs = 0`; both replicas (18201/18202) probed.

## External blocker status re-confirmed (dispatch capture, 2026-10-17)

Unchanged from rounds 110–111, re-checked against the fresh dispatch capture:

- **Row 3** (≥ `PROMOTION_MIN_SUSTAIN_SECONDS = 14400` vs pack `420.05`):
  above any in-lane round window; background execution prohibited; no
  production Compose runner is designated in-lane.
- **Row 8** (soak of the exact RC artifact): parent **#89 open**, RC PR
  **#1672 open draft** (`15ce4681`) — no RC artifact exists to soak.
- **Row 5**: contrary-by-design per closed **#842**'s explicit fail-safe
  branch ("or explicitly fail safe within the claimed policy"), regression-
  locked as a finding by the test above; disposition recorded in round 111.

## Disposition

The lane's in-repo work is complete and green at the dispatched head: rows
1–2, 4, 6–7, 10 carry verified bounded evidence bound to the current
production identity (byte-identical since the soaked head) and must be
re-evidenced at the eventual promotion commit; rows 3 and 8 are externally
blocked on the release owner (RC designation under parent #89; ≥ 4 h
production window); row 5 is contrary-by-design per #842. Nothing in-repo is
repairable by this lane; the escalation stays with the release owner.

Progress: checked 1 issue; done 0 acceptance-complete issues (rows 3, 8
externally blocked; row 5 contrary-by-design); skipped 0; validation errors
0; escalated 1 (RC designation under parent #89 — unchanged); inventory
delta 0 (no tests added or removed by this round; the harness note
`docs/testing/inventory-notes/m3a-860-multi-replica-soak.md` already covers
the tooling and remains accurate); repairs 0 (the one standing verifier
finding was already resolved by the develop merge and is re-proven green
here).
