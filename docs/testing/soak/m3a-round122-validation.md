# Issue #860 — round 122 (job 04689b69) validation at the dispatched head 0a6f92e6a

**Not promotion evidence or integration approval.** This round is the fresh
execution for job `04689b6925034801ba3bd7b241096a34`, dispatched at head
`0a6f92e6a` (= the round-121 record commit; tree clean at start and at end +
this record). The job directory contained **no `check-*.log` files** at start
— zero driver-executed checks — so every result below was produced fresh by
this round, independently of round 121's record. Prior artifact read:

- `/home/dev/maistro/jobs/4f709d400eaf42bd890c7e8146ae03c7/result.json`:
  verdict `BLOCKED`, rows 3+8 externally blocked. This round re-derived both
  determinations itself (see External blockers) instead of carrying them
  forward.

## Snapshot

- Start head `0a6f92e6a` — exactly the dispatched head; `git status
  --porcelain` empty. End head: same + this record.
- `git fetch origin` then `git rev-parse origin/develop` = `ab8b3737f`
  (unchanged) and `git merge-base --is-ancestor origin/develop HEAD`
  passes — **no develop drift, no sync conflict**. The standing "BLOCKED"
  attention request is not a merge conflict (see Disposition).
- **Production identity binding intact**: `git diff 5a59c724a..HEAD
  --name-only -- . ':(exclude)docs' ':(exclude)*.md'` is **empty** —
  production code is byte-identical to the soaked head `5a59c724a`, so the
  round-109 evidence pack (`hashes.git_head = 5a59c724a…`, `git_clean =
  true`) remains bound at this head.

## Deterministic battery at `0a6f92e6a` (all green, this round)

| Gate | Result |
| --- | --- |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3,301 files already formatted |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (vulture-ratchet.yml CI-exact arguments) | rc=0: **1,322 reviewed identities → 1,322 findings**, `unclassified: 0`; base `ab8b3737fa64`, candidate `0a6f92e6af5f`; ledger unamended |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_gitleaksignore_contract.py tests/test_prod_stack_boot_contract.py -q` | **89 passed** |
| `tests/test_soak_promotion_gates.py::test_replica_selection_has_an_independent_production_allowance` re-run by name | **2 passed** — parametrized over `authenticated ∈ {False, True}` (tests/test_soak_promotion_gates.py:438) |
| `packages/maistro-core/tests/persistence/test_pg_learnings.py::test_ensure_schema_fences_ddl_behind_advisory_lock` re-run by name | **1 passed** — formally re-proves closure of the 98a11313 `check-3.log` finding at this head |
| `uv run mypy` with ci.yml's exact ten-tree arguments (core, server, turing, canvas, bootstrap, registry, evolve, rsi, design, ext-harness) | **Success: no issues found in 1,057 source files** |
| `uv run python scripts/check-suite-inventory.py` | ok: **17/17 suites** match the recorded inventory |
| `uv run python scripts/check-ratchet-provenance.py` | OK: **53** quality JSON consumer(s) have explicit provenance; 0 lifecycle violations; no candidate-approved expansion |
| `uv run python scripts/check-shipped-surface-truth.py` | Shipped-surface truth matrix is complete |

No tests were added or changed, so there is no suite-inventory delta and no
`docs/testing/inventory-notes/` entry is required.

## Promotion gates + evidence-pack integrity (reproduced live, this round)

`failed_promotion_checks` (scripts/soak/run_soak.py:758) applied in-process
to `docs/testing/soak/evidence/m3a-round109-shakedown.json` at this head
returns exactly **`['sustain_duration', 'exact_rc_artifact']`** — identical
to rounds 109–121. Everything else re-verified from the raw document:

- Functional gates all true under `thresholds.checks`:
  `exactly_once_task_admission = true`,
  `exactly_once_schedule_occurrence = true`, `rate_limit_enforced = true`,
  `replica_2_rejoined = true`, `lb_failover_bounded` (ok, observed
  5xx+conn-errors **0** vs budget 4320.0),
  `nonterminal_runs_after_settle` (count 0, ok), `task_admission_availability`
  (ratio 1.0, ok), plus `graceful_drain` with `required = true`,
  `signal = SIGTERM`, `drained = true`, `drain_5xx = 0`,
  `drain_conn_errors = 0`.
- `sustain_duration`: `{ok: false, observed_seconds: 420.05,
  minimum_seconds: 14400}` against `PROMOTION_MIN_SUSTAIN_SECONDS = 14_400`
  (scripts/soak/run_soak.py:69) — the only functional shortfall.
- `exact_rc_artifact`: `{ok: false, reason: "not the exact production
  Compose image and configuration", topology: "host-uvicorn-preflight"}` —
  `preflight_artifact_check` deliberately has no CLI override
  (scripts/soak/run_soak.py:744).
- `final_runs_by_status = completed=2796 cancelled=1`,
  `nonterminal_runs = 0`.
- Pack integrity re-derived from the raw document:
  `hashes.nginx_conf_sha256` matches `sha256(scripts/soak/nginx-soak.conf)`
  on disk; the committed
  `m3a-round109-shakedown-nginx-soak-rendered.conf` matches both the pack's
  recorded `nginx_rendered_conf_sha256` **and** a fresh manual
  `host.docker.internal → 192.168.8.198` substitution of the template using
  the pack's recorded `host_gateway_ipv4` (the exact replacement
  `render_nginx_conf` performs, scripts/soak/run_soak.py:404) — all three
  agree byte-for-byte.
- Row-5 scope string re-read from the pack:
  `rate_limit.enforcement_scope = "process-local; aggregate budget is
  replica count times limit"`; the row-7 repair remains in production code
  (`SELECT pg_advisory_xact_lock`, packages/maistro-core/src/maistro/persistence/pg_learnings.py:216).

## External blocker status re-confirmed (fresh dispatch capture, 2026-10-17T12:05Z)

Unchanged from rounds 110–121, re-derived from this round's own
`dispatch-context.json` (69 sources, `complete_for_scope: true`), not
carried forward:

- **Row 3** (sustained load ≥ `PROMOTION_MIN_SUSTAIN_SECONDS = 14_400` vs
  pack 420.05): a ≥ 4 h sustained run is above any in-lane round window;
  background execution is prohibited; no production Compose runner is
  designated in-lane.
- **Row 8** (long soak of the exact RC artifact): parent **#89 ("M3-A7 —
  Run RC soak and byte-equivalent final promotion") open with 0 comments**
  (no RC designation recorded anywhere in the capture), RC PR **#1672 open,
  `draft: true`, not merged** (head `15ce4681c`). No RC artifact exists to
  soak; `preflight_artifact_check` cannot sign promotion by design.
- **Row 5**: contrary-by-design per closed **#842** whose explicit
  fail-safe branch permits a process-local limiter advertised as such; the
  pack records exactly that scope and the aggregate budget (replica count ×
  per-process limit), regression-locked by
  `test_replica_selection_has_an_independent_production_allowance` (green
  above, re-run by name in both parameterizations).
- The latest 860 comments in the capture (through 2026-10-17T11:49:46Z) are
  bot progress markers only — no release-owner response, no RC designation,
  no threshold change.

## Disposition

The lane's in-repo work is complete and green at the dispatched head: rows 1,
2, 4, 6, 7, 9 and 10 carry verified bounded evidence bound to the current
production identity (byte-identical since soaked head `5a59c724a`) and must
be re-evidenced at the eventual promotion commit; rows 3 and 8 remain
externally blocked on the release owner (RC designation under parent #89 and
a ≥ 4 h production window); row 5 is contrary-by-design per #842. This round
independently re-derived the prior BLOCKED determination (job 4f709d40) and
found nothing in-repo repairable: every gate is green, the evidence pack is
hash-tied and intact, and the shortfall rows require the release owner, not
this lane. The standing "BLOCKED" attention request reflects that external
dependency — it is not a develop sync conflict (`origin/develop` =
`ab8b3737f`, already an ancestor) and not a failing gate.

Progress: `{checked: 1, done: 0 (externally blocked), skipped: 0, errors: 0,
next: exact-RC production soak after release-owner RC designation}`.
