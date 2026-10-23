# Issue #860 — bounded repair bba708c5

## Frozen scope

- One item: issue #860 on `auto-860`, starting at
  `035c08655b7e1bd4a58b650f01e6f0d42c005dea`, supplied develop base
  `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Inspect supplied dispatch context/prior failure, repository instructions,
  relevant ADRs, existing soak harness and adjacent tests.
- Candidate edits restricted to this report and `quality/vulture-baseline.json`
  if the prescribed scan identifies reviewed retained debt. No speculative
  runtime repair, new execution authority, or remote actions.
- Initial worktree clean; starting HEAD matches dispatch. No salvage required.
- Job directory contains no `check-*.log`; inspect the explicitly supplied prior
  `98a11313167b41a98a420abfda80c292/check-3.log` instead.

## Assumptions and checkpoint

This is a writer CI-repair round, not approval to promote. The prior result says
BLOCKED and identifies missing exact-RC evidence; those assertions must be
rechecked. No exact promoted artifact/configuration is designated in the issue
body. Do not substitute this worktree or fabricated telemetry for that artifact.

First executed result: prescribed vulture scan exits 0, 1,323 findings / 1,323
reviewed identities, zero unclassified or never-allowlist findings. No ledger
amendment justified. The supplied historical `check-3.log` is instead a failing
schema-fence test (24 observed DDL statements versus 21 expected). Revalidate
that exact test before deciding whether any repair remains necessary.

## Executed validation

Commands ran in this worktree with 600–1,200 second timeouts; logs are under
`/tmp/860-bba708c5-*.log` (local diagnostics, not RC evidence).

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS; 1,323 reviewed / observed identities. Gate selected base `4aa68edc0b6b`; no grant or ledger edit. |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped. Historical failure does not reproduce. |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 82 passed. Includes real production limiter instances and fail-closed promotion checks. |
| `uv run ruff check .` | PASS. |
| `uv run ruff format --check .` | PASS; 3,270 files already formatted. |
| `uv run python scripts/check-ratchet-provenance.py` | PASS; 53 consumers. |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS. |

The current schema-fence test independently enumerates all 24 DDL statements,
including the three validation-audit columns missing from the historical log
(`packages/maistro-core/tests/persistence/test_pg_learnings.py:175-179`). No
assertion relaxation is needed. Database tests remain skipped, not claimed as
live two-replica validation. No new tests or suite-count changes; no inventory
note required.

## Architecture and reachable acceptance

Read repository `AGENTS.md`, documentation authority map, accepted
ADR-081426-1f7c (Attempt ID is physical execution identity), ADR-081626-f383
(durable execution lease/fence), ADR-082126-f69c (recurrence produces canonical
Runs, not a second runtime), and ADR-085 (per-principal limits). Inspected the
existing driver, load profile, adjacent tests, and production limiter. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`. Admission deduplication does not
prove physical execution uniqueness. Process-local per-principal enforcement
does not establish the stronger issue criterion of replica-selection non-bypass.
No architectural reconciliation warrants introducing a second authority here.

All ten acceptance criteria were reviewed; none is certified by this round:

| Criterion | Fresh evidence / disposition |
| --- | --- |
| Representative RC load profile | **UNVERIFIED.** Driver `scripts/soak/run_soak.py:1373-1395` uses one credential and a health/task/receipt/metrics mix. `docs/testing/soak/m3a-load-profile.md:152` explicitly lists missing concurrent users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and Goal/background work. |
| Two application replicas | **UNVERIFIED for exact RC.** `run_soak.py:730-742` declares host-uvicorn preflight, not promoted Compose. ASGI transports in the executed tests are not deployed replicas. |
| Sustained saturation, growth, reclaim, retry, leaks and restart observations | **UNVERIFIED.** No long-running load was executed this round; unit tests supply no long-window telemetry. |
| No duplicate physical schedule/task/Run/Attempt work and Goal reconciliation | **UNVERIFIED.** `run_soak.py:1044-1077` explicitly cancels the admitted schedule probe Run without executing it. This cannot prove Attempt effects or Goal reconciliation. |
| Rate/security/degraded non-bypass under concurrency | **UNVERIFIED overall; allowance gap reproduced.** Both cases of `tests/test_soak_promotion_gates.py:439` pass against production middleware: the same identity gets `[200, 200, 429]` independently on each instance. `packages/maistro-server/src/maistro_server/api/rate_limit.py:32-37,96` documents and constructs process-local limiters. This is not shared-budget proof. |
| Required telemetry and pass/fail thresholds | **UNVERIFIED.** `run_soak.py:1410-1423` samples driver loop lag, not application loop lag. No new complete PostgreSQL, worker, queue, resource or error series collected. |
| Kill/restart during active work with drain/fencing/recovery | **UNVERIFIED.** `run_soak.py:1427-1450` chooses the signal time by elapsed time, not observed active Attempt. Rejoin and terminal Run totals do not prove physical recovery. |
| Long unchanged exact-RC soak | **UNVERIFIED.** `run_soak.py:1551` always emits the failing preflight artifact check. Executed promotion tests reject missing/null/preflight artifact evidence even with synthetic four-hour duration. No immutable promotion RC/config was selected or deployed this round. |
| Findings filed/reclassified before promotion | Local disposition recorded here; external filing/reclassification **UNVERIFIED**. No remote mutation permitted or performed. |
| Machine/human evidence tied to exact image/package/commit/config hashes | **UNVERIFIED for RC.** This source-validation report names starting HEAD; it is not an image/config-bound production evidence pack. |

## Final disposition and next prerequisite

**BLOCKED** on production acceptance, not on the reported CI gate. Historical
failure and vulture mismatch do not reproduce. No source/test/ledger repair is
justified by the observed results; changing those would be speculative.

Only this report changes. Before another soak attempt, select the immutable
promotion artifact/configuration and representative workloads; resolve or
explicitly disposition the replica-selection allowance gap at the owning
invariant; instrument physical Attempts, fencing/reclaim and application health;
then run a fresh unchanged exact-RC long soak and publish hash-bound evidence.
Another identical CI-repair dispatch cannot supply these missing prerequisites.
No production soak, full-tree pytest, or live database integration was run.

Progress: checked 1 issue; CI investigation done; acceptance-complete 0; skipped
issues 0; fresh validation errors 0. Commit this checkpoint locally; not
integration approval or issue closure.
