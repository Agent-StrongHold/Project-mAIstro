# Issue #860 — round 120 (job 30918ac9) validation at the dispatched head f8f25d313

**Not promotion evidence or integration approval.** This round is the fresh
execution for job `30918ac917144a5ab0b394c6fe32266c`, dispatched at head
`f8f25d313` (= the round-119 record commit; tree clean at start and at end +
this record). The job directory contained **no `check-*.log` files** at start
— zero driver-executed checks — so every result below was produced fresh by
this round. Prior artifacts read, neither naming an open in-repo failure:

- `/home/dev/maistro/jobs/e0aa9a3019b94f7bb05c2f2f95fa63c9/result.json`:
  `failure_kind: provider_error` (openrouter 404, model unavailable),
  `checks: []`, `agent_exit: 0` — a provider failure with **zero executed
  checks**, not a validation failure. Nothing repairable.
- The standing prior finding `/home/dev/maistro/jobs/98a11313167b41a98a420abfda80c292/check-3.log`
  (`test_ensure_schema_fences_ddl_behind_advisory_lock`, `assert 24 == 21`)
  remains closed: `git merge-base --is-ancestor cd77bb81c HEAD` passes and
  the test passes **by name** at this head — see the battery table.

## Snapshot

- Start head `f8f25d313` — exactly the dispatched head; `git status
  --porcelain` empty. End head: same + this record.
- `git fetch origin`: `origin/develop` = `ab8b3737f` — the declared base —
  and `git merge-base --is-ancestor origin/develop HEAD` passes. **No develop
  drift; no sync conflict.** The standing "BLOCKED" attention request is not
  a merge conflict (see Disposition). (The `refname 'origin/develop' is
  ambiguous` warning resolves to the same object: a stray local branch
  `refs/heads/origin/develop` and `refs/remotes/origin/develop` both point at
  `ab8b3737f`.)
- **Production identity binding intact**: `git diff 5a59c724a..HEAD
  --name-only -- . ':!docs'` is **empty** — production code is
  byte-identical to the soaked head `5a59c724a`, so the round-109 evidence
  pack (`hashes.git_head = 5a59c724a…`, `git_clean = true`) remains bound at
  this head.

## Deterministic battery at `f8f25d313` (all green, this round)

| Gate | Result |
| --- | --- |
| `uv sync --locked --extra dev` | ok (resolved 256 / checked 214 packages) |
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 3,301 files already formatted |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (vulture-ratchet.yml CI-exact arguments) | rc=0: **1,322 reviewed identities → 1,322 findings**, `unclassified: 0`; base `ab8b3737fa64`, candidate `f8f25d31395d`; ledger unamended |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_gitleaksignore_contract.py tests/test_prod_stack_boot_contract.py -q` | **89 passed**, including the row-5 regression lock `test_replica_selection_has_an_independent_production_allowance` (re-run by name: 2 passed) |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -q` | **38 passed, 6 skipped** (skips require `MAISTRO_TEST_PG_DSN`); `test_ensure_schema_fences_ddl_behind_advisory_lock` re-run **by name: 1 passed**, formally re-proving closure of the 98a11313 `check-3.log` finding at this head |
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
to rounds 109–119. Everything else re-verified from the raw document:

- Functional gates all true under `thresholds.checks`:
  `exactly_once_task_admission`, `exactly_once_schedule_occurrence`,
  `rate_limit_enforced`, `lb_failover_bounded`, `replica_2_rejoined`,
  `nonterminal_runs_after_settle`, `task_admission_availability`, plus
  `graceful_drain` with `required = true`, `signal = SIGTERM`,
  `drain_5xx = 0`, `drained = true`.
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
  on disk; `hashes.nginx_rendered_conf_sha256` (`86291c53ab2a81fd…`) matches
  both the template with the pack's recorded `hashes.host_gateway_ipv4`
  (`192.168.8.198`) substituted via the exact
  `host.docker.internal → ip` replacement of `render_nginx_conf`
  (scripts/soak/run_soak.py:395) **and** the committed
  `m3a-round109-shakedown-nginx-soak-rendered.conf`.
- Row-5 scope string re-read from the pack:
  `rate_limit.enforcement_scope = "process-local; aggregate budget is
  replica count times limit"`; the row-7 repair remains in production code
  (`SELECT pg_advisory_xact_lock`, packages/maistro-core/src/maistro/persistence/pg_learnings.py:216).

## External blocker status re-confirmed (fresh dispatch capture, 2026-10-17)

Unchanged from rounds 110–119, re-derived from this round's own
`dispatch-context.json` (69 sources, `complete_for_scope: true`), not carried
forward:

- **Row 3** (sustained load ≥ `PROMOTION_MIN_SUSTAIN_SECONDS = 14_400` vs
  pack 420.05): a ≥ 4 h sustained run is above any in-lane round window;
  background execution is prohibited; no production Compose runner is
  designated in-lane.
- **Row 8** (long soak of the exact RC artifact): parent **#89 ("M3-A7 — Run
  RC soak and byte-equivalent final promotion") open with 0 comments** (no RC
  designation recorded anywhere in the capture), RC PR **#1672 open,
  `draft: true`, not merged** (head `15ce4681c`). No RC artifact exists to
  soak; `preflight_artifact_check` cannot sign promotion by design.
- **Row 5**: contrary-by-design per closed **#842** (`state_reason:
  completed`) whose explicit fail-safe branch permits a process-local limiter
  advertised as such; the pack records exactly that scope and the aggregate
  budget (replica count × per-process limit), regression-locked by
  `test_replica_selection_has_an_independent_production_allowance` (green
  above, re-run by name).

## Disposition

The lane's in-repo work is complete and green at the dispatched head: rows 1,
2, 4, 6, 7, 9 and 10 carry verified bounded evidence bound to the current
production identity (byte-identical since soaked head `5a59c724a`) and must
be re-evidenced at the eventual promotion commit; rows 3 and 8 remain
externally blocked on the release owner (RC designation under parent #89 and
a ≥ 4 h production window); row 5 is contrary-by-design per #842. The
immediately-prior attempt died on a provider 404 with zero checks
(e0aa9a30), and the older 98a11313 schema-fence finding stays closed and
re-proven at this head. Nothing in-repo is repairable by this lane; the
escalation stays with the release owner, and that external dependency is what
the standing "BLOCKED" attention request reflects — it is not a develop sync
conflict (`origin/develop` is already an ancestor) and not a failing gate
(every gate above is green).

Progress: `{checked: 1, done: 0 (externally blocked), skipped: 0, errors: 0,
next: exact-RC production soak after release-owner RC designation}`.
