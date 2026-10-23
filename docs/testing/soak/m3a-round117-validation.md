# Issue #860 — round 117 (job 334c67c0) validation at the dispatched head bebea1cda

**Not promotion evidence or integration approval.** This round is the first
execution for job `334c67c02cc44743b9a6a7075284d827`, dispatched at head
`bebea1cda` (= the round-116 record commit; tree clean at start and at end +
this record). The job directory contained **no `check-*.log` files** at start
— zero driver-executed checks — so all nine `check-N.log` files below were
produced fresh by this round in the job directory. The round-116 "BLOCKED"
disposition is re-derived, not carried forward: its two externally blocked
rows were re-checked against this round's fresh dispatch capture, and nothing
about them moved. The standing prior-round block ("worker made no commit;
clean tree is not proof of repair") is addressed by this very record: the
round ends in a commit containing this validation evidence.

## Snapshot

- Start head `bebea1cda` — exactly the dispatched head; tree clean (check-0:
  0 dirty entries). End head: same + this record.
- `git fetch origin` this round: `origin/develop` is still `ab8b3737f` — the
  declared base, and `git merge-base --is-ancestor` confirms it is already an
  ancestor of HEAD. **No develop drift; no sync needed** (the standing
  "BLOCKED" attention request is not a sync conflict; see Disposition).
- **Production identity binding intact**: `git diff 5a59c724a..HEAD
  --name-only -- . ':!docs'` is **empty** (check-0), so the round-109
  evidence pack (`hashes.git_head = 5a59c724a20e…`, `git_clean = true`)
  remains bound to byte-identical production code at this head.

## Deterministic battery at `bebea1cda` (all green, this round)

| Gate | Result |
| --- | --- |
| `uv sync --locked --extra dev` | ok (resolved 256 / checked 214 packages; job check-0 context) |
| `uv run ruff check .` | All checks passed (check-1) |
| `uv run ruff format --check .` | 3,301 files already formatted (check-2) |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (vulture-ratchet.yml CI-exact arguments) | rc=0: **1,322 reviewed identities → 1,322 findings**; base `ab8b3737fa64`, candidate `bebea1cda132`; ledger unamended (check-3) |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_gitleaksignore_contract.py tests/test_prod_stack_boot_contract.py -q` | **89 passed** (check-4), including the row-5 regression lock `test_replica_selection_has_an_independent_production_allowance` (tests/test_soak_promotion_gates.py:439) |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -q` | **38 passed, 6 skipped** (check-5; skips require `MAISTRO_TEST_PG_DSN`) |
| `uv run mypy` with ci.yml's exact package arguments (10 source trees incl. `maistro-evolve`, `maistro-rsi`, `maistro-design`, `maistro-ext-harness`) | **Success: no issues found in 1,057 source files** (check-6) |
| `uv run python scripts/check-suite-inventory.py` | ok: **17/17 suites** match the recorded inventory (check-7) |

## Promotion gates + evidence-pack integrity (check-8, reproduced live)

`failed_promotion_checks` (scripts/soak/run_soak.py:762) applied in-process
to `docs/testing/soak/evidence/m3a-round109-shakedown.json` at this head
returns exactly **`['sustain_duration', 'exact_rc_artifact']`** — identical
to rounds 109–116. Everything else about the pack re-verified from the raw
document this round:

- Functional gates all true under `thresholds.checks`:
  `exactly_once_task_admission`, `exactly_once_schedule_occurrence`,
  `rate_limit_enforced`, `lb_failover_bounded`, `replica_2_rejoined`,
  `nonterminal_runs_after_settle`, `task_admission_availability` (via the
  same `_check_ok` the production gate uses), plus `graceful_drain` with
  `required = true`, `signal = SIGTERM`, `drain_5xx = 0`, `drained = true`.
- `sustain_duration` gate: `{minimum_seconds: 14400, observed_seconds:
  420.05, ok: false}` against `PROMOTION_MIN_SUSTAIN_SECONDS = 14_400`
  (scripts/soak/run_soak.py:69) — the only functional shortfall.
- `exact_rc_artifact` gate: `ok: false`, reason "not the exact production
  Compose image and configuration", topology `host-uvicorn-preflight`
  (`preflight_artifact_check` deliberately has no CLI override,
  scripts/soak/run_soak.py:740).
- `final_runs_by_status = completed=2796 cancelled=1`,
  `nonterminal_runs = 0`.
- Pack integrity re-derived from the raw document, both hashes re-computed
  in-process (check-8): `hashes.nginx_conf_sha256` (`8e4d447a…`) matches
  `sha256(scripts/soak/nginx-soak.conf)` on disk, and
  `hashes.nginx_rendered_conf_sha256` (`86291c53…`) matches the template with
  the pack's recorded `host_gateway_ipv4` (`192.168.8.198`) substituted via
  `render_nginx_conf`'s exact replacement (scripts/soak/run_soak.py:396).
- Row-5 scope string re-read from the pack this round:
  `rate_limit.enforcement_scope = "process-local; aggregate budget is
  replica count times limit"`.

## External blocker status re-confirmed (fresh dispatch capture, 2026-10-17T09:55Z)

Unchanged from rounds 110–116, re-read from this round's own
`dispatch-context.json` (69 sources, `complete_for_scope: true`):

- **Row 3** (sustained load ≥ `PROMOTION_MIN_SUSTAIN_SECONDS = 14_400` vs
  pack 420.05): a ≥ 4 h sustained run is above any in-lane round window;
  background execution is prohibited; no production Compose runner is
  designated in-lane.
- **Row 8** (long soak of the exact RC artifact): parent **#89 ("M3-A7 —
  Run RC soak and byte-equivalent final promotion") open with 0 comments**
  (no RC designation recorded anywhere in the capture), RC PR **#1672 open,
  `draft: true`, `merged: false`, `mergeable_state: behind`** (head
  `15ce4681`). No RC artifact exists to soak; `preflight_artifact_check`
  cannot sign promotion by design.
- **Row 5**: contrary-by-design per closed **#842** (`state_reason:
  completed`) whose explicit fail-safe branch reads "Distributed/supported
  multi-replica deployments share enforcement state **or explicitly fail
  safe within the claimed policy**; a process-local limiter cannot be
  advertised as cluster-wide". The pack's recorded `enforcement_scope`
  claims exactly that process-local fail-safe policy, and the aggregate
  budget is replica-count × per-process limit, regression-locked as a
  finding by `test_replica_selection_has_an_independent_production_allowance`
  (green in check-4).

## Disposition

The lane's in-repo work is complete and green at the dispatched head: rows 1,
2, 4, 6, 7 and 10 carry verified bounded evidence bound to the current
production identity (byte-identical since soaked head `5a59c724a`) and must
be re-evidenced at the eventual promotion commit; rows 3 and 8 remain
externally blocked on the release owner (RC designation under parent #89 and
a ≥ 4 h production window); row 5 is contrary-by-design per #842. Nothing
in-repo is repairable by this lane; the escalation stays with the release
owner, and that external dependency is what the standing "BLOCKED" attention
request actually points at.

Progress: checked 1 issue; done 0 acceptance-complete issues (rows 3, 8
externally blocked; row 5 contrary-by-design); skipped 0; validation errors
0; escalated 1 (RC designation under parent #89 — unchanged);
**inventory delta 0** (no tests added or removed; `check-suite-inventory.py`
reports 17/17 and `docs/testing/inventory-notes/m3a-860-multi-replica-soak.md`
remains accurate); repairs 0 (no repo defect found this round; the two failed
promotion gates are the documented external dependencies, re-proven current
against the fresh capture).
