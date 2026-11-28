# Issue #860 — round 115 (job f88dc19a) validation at the round-114 record head

**Not promotion evidence or integration approval.** The dispatched run chain
since round 114: job `320ac61fa3` died on a provider timeout before executing
any command (`result.json`: `error: "provider error … Request timed out."`,
`failure_kind: provider_error`, `checks: []`, zero tree effect — that job's
"worker requested attention: BLOCKED" block was the provider death, not a
repo-state problem), and this round is the first re-execution at head
`bb4e157f9`. This round re-proves the deterministic battery at the dispatched
head with zero driver-executed checks (the job directory contained **no
`check-*.log` files** at start; every `check-N.log` below was produced fresh
by this round in the job directory). No source, test, or ledger file was
authored or modified; the only tree content added is this record.

## Snapshot

- Start head `bb4e157f9` — exactly the dispatched head; tree clean. End head:
  same + this record.
- `git fetch origin`: `origin/develop` is still `ab8b3737f` — the declared
  base, already an ancestor of HEAD. **No develop drift; no sync needed**
  (so the standing "BLOCKED" block was not a sync conflict).
- **Production identity binding intact**: `git diff 5a59c724a..HEAD
  --name-only` filtered to non-`docs/` paths is **empty**, so the round-109
  evidence pack (`hashes.git_head = 5a59c724a20e…`, `git_clean = true`,
  `git_status_sha256` = empty-blob sha) remains bound to byte-identical
  production code at this head.

## Deterministic battery at `bb4e157f9` (all green, this round)

| Gate | Result |
| --- | --- |
| `uv sync --locked --extra dev` | ok (check-0) |
| `uv run ruff check .` | All checks passed (check-1) |
| `uv run ruff format --check .` | 3,301 files already formatted (check-2) |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (vulture-ratchet.yml CI-exact arguments) | rc=0: **1,322 reviewed identities → 1,322 findings**; base `ab8b3737fa64`, candidate `bb4e157f9d8a`; no ledger amendment (check-3) |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_gitleaksignore_contract.py tests/test_prod_stack_boot_contract.py -q` | **89 passed** (check-4), including the row-5 regression lock `test_replica_selection_has_an_independent_production_allowance` (tests/test_soak_promotion_gates.py:439) |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -q` | **38 passed, 6 skipped** (check-5; skips require `MAISTRO_TEST_PG_DSN`) — job 98a11313's check-3 finding file, green here too |
| `uv run mypy` with ci.yml's exact package arguments (10 source trees incl. `maistro-evolve`, `maistro-rsi`, `maistro-design`, `maistro-ext-harness`) | **Success: no issues found in 1,057 source files** (check-6) |
| `uv run python scripts/check-suite-inventory.py` | ok: **17/17 suites** match the recorded inventory (check-7) |

## Promotion gates + evidence-pack integrity (check-8, reproduced live)

`PYTHONPATH=scripts/soak` + `failed_promotion_checks(scripts/soak/run_soak.py)`
applied to `docs/testing/soak/evidence/m3a-round109-shakedown.json` at this
head exits with exactly **`['sustain_duration', 'exact_rc_artifact']`** —
identical to rounds 109–114. The eight functional gates pass under
`thresholds.checks` (`exactly_once_task_admission`,
`exactly_once_schedule_occurrence`, `rate_limit_enforced`,
`lb_failover_bounded`, `replica_2_rejoined`, `nonterminal_runs_after_settle`,
`task_admission_availability`, and `graceful_drain` with `required = true`,
SIGTERM, 0 drain 5xx). Pack integrity, re-derived this round from the raw
document rather than any round's prose:

- `hashes.nginx_conf_sha256` (`8e4d447a…`) matches the template on disk
  (`sha256(scripts/soak/nginx-soak.conf)`), **and**
  `hashes.nginx_rendered_conf_sha256` (`86291c53…`) matches the template
  rendered with the pack's recorded `host_gateway_ipv4` (`192.168.8.198`)
  via `render_nginx_conf`'s exact substitution — both verified by hashing
  in-process (check-8).
- `sustain_seconds = 420.05` (requested 420) against
  `sustain_duration.minimum_seconds = 14400`
  (`PROMOTION_MIN_SUSTAIN_SECONDS`, scripts/soak/run_soak.py:69) — the only
  functional shortfall; `exact_rc_artifact.ok = false` with the by-design
  reason "not the exact production Compose image and configuration"
  (`preflight_artifact_check` has deliberately no CLI override).
- `final_runs_by_status = completed=2796 cancelled=1`, `nonterminal_runs = 0`.

## External blocker status re-confirmed (dispatch capture, 2026-10-17T07:47Z)

Unchanged from rounds 110–114, re-checked against this round's fresh dispatch
capture:

- **Row 3** (soak ≥ `PROMOTION_MIN_SUSTAIN_SECONDS = 14400`; scripts/soak/
  run_soak.py vs pack 420.05): a ≥ 4 h sustained run is above any in-lane
  round window; background execution is prohibited; no production Compose
  runner is designated in-lane.
- **Row 8** (soak of the exact RC artifact): parent **#89 open, 0 comments**
  (no RC designation recorded), RC PR **#1672 still open draft**
  (`15ce4681`, `mergeable_state: behind`). No RC artifact exists to soak;
  host-preflight cannot sign promotion by design.
- **Row 5**: contrary-by-design per closed **#842**'s explicit fail-safe
  branch ("or explicitly fail safe within the claimed policy"); the aggregate
  budget is replica-count × per-process limit, recorded in the pack's
  `enforcement_scope`, and regression-locked as a finding by
  `test_replica_selection_has_an_independent_production_allowance`.

## Disposition

The lane's in-repo work is complete and green at the dispatched head: rows 1,
2, 4, 6, 7 and 10 carry verified bounded evidence bound to the current
production identity (byte-identical since soaked head `5a59c724a`) and must be
re-evidenced at the eventual promotion commit; rows 3 and 8 remain externally
blocked on the release owner (RC designation under parent #89 and a ≥ 4 h
production window); row 5 is contrary-by-design per #842. Nothing in-repo is
repairable by this lane; the escalation stays with the release owner.

Progress: checked 1 issue; done 0 acceptance-complete issues (rows 3, 8
externally blocked; row 5 contrary-by-design); skipped 0; validation errors 0;
escalated 1 (RC designation under parent #89 — unchanged); **inventory delta
0** (no tests added or removed; `check-suite-inventory.py` reports 17/17 and
the harness note `docs/testing/inventory-notes/m3a-860-multi-replica-soak.md`
remains accurate); repairs 0 (the prior "BLOCKED" was a provider death at job
`320ac61fa3` with zero commands executed, and the one standing verifier
finding from job 98a11313 stays resolved — re-proven green at check-5).
