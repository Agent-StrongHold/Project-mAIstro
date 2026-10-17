# Issue #860 repair checkpoint — 3692e484

## Frozen scope

- Assigned issue: #860 only; branch `auto-860`.
- Starting HEAD: `50d7c73fac3aafa82403cafb36d547b84a6918cf`.
- Supplied base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Worktree initially clean; no incoming edits to salvage.
- Inspect supplied dispatch context, previous result, prior check-3.log,
  repository instructions, relevant ADRs, existing soak runner and adjacent tests.
- Run the requested exact vulture scan; edit retained/dead identities only if
  actual scan evidence requires it. Ledger edits are explicitly authorized for
  this CI-repair lane, not authorization/grant changes.
- Candidate implementation scope: `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, corresponding inventory note, and
  `quality/vulture-baseline.json` only if needed by actual findings.
- No GitHub mutations, deployment assumptions, gate weakening, or new execution
  authority. Acceptance evidence may remain blocked rather than be fabricated.

## Initial observations

The current job directory contains no `check-*.log` files. The supplied prior
result reports BLOCKED, not promotion approval. Those claims are not assumed
verified; current checks follow. The supplied older check-3.log exists.

Ambiguity: a CI-repair lane also requests full production soak acceptance.
Proceed by validating the exact gate and reviewing reachable acceptance paths;
local unit checks cannot certify an unavailable exact-RC deployment.

## Executed validation

All commands below ran in the assigned worktree with 1,000–1,200 second timeouts.

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS; 1,323 findings / 1,323 reviewed identities, zero unclassified or forbidden identities. Scanner-selected base `4aa68edc0b6b`. No ledger amendment warranted.
- Historical supplied `check-3.log`: schema assertion mismatch, 24 statements versus 21; not a vulture failure.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`: 37 passed, 6 skipped. Historical failure not reproduced; live database coverage remains skipped.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: 82 passed. Includes actual production limiter instances reproducing independent per-replica allowances and synthetic CLI evidence rejected without exact-RC proof.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3,270 files formatted.

No implementation/test edits are justified by these gate results. No tests added
or removed; inventory delta is zero. Production acceptance review follows.

- `uv run python scripts/check-ratchet-provenance.py`: PASS, 53 consumers;
  two non-fatal invalid-escape SyntaxWarnings.
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `uv run python scripts/check-backlog-consistency.py`: PASS, 168 items.
- `git diff --check`: PASS.

## Architecture reconciliation

Read `AGENTS.md`, `docs/README.md`, accepted ADR-081226-69ee,
ADR-081426-1f7c, ADR-081626-f383, ADR-082526-b36a and ADR-085; inspected
existing soak tests, the driver, profile and production rate-limit middleware.
The canonical `Goal -> Graph -> Run -> NodeRun -> Attempt` model is unchanged.
ExecutionRuntime identity is Attempt ID, not an admission receipt. Lease
renewal/reclamation supplements the original fencing contract. Per-principal
rate-limit identity does not imply shared multi-replica allowance; neither the
ADR nor documented process-local limits proves #860's non-bypass criterion.
No competing execution, storage, authorization or event authority introduced.

## Acceptance review against current reachable behavior

The acceptance list below comes from the supplied immutable dispatch issue body,
not from prior verification claims. No production soak was executed this round.

| Criterion | Evidence and disposition |
| --- | --- |
| Representative RC profile | **UNVERIFIED.** `scripts/soak/run_soak.py:1373-1395` uses one credential and health/task/receipt/metrics traffic. Concurrent Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and Goal/background workloads are explicitly missing in `docs/testing/soak/m3a-load-profile.md:152`. |
| At least two deployed application replicas | **UNVERIFIED for RC.** The driver identifies its host-uvicorn topology as preflight at `scripts/soak/run_soak.py:730-742`. Two ASGI instances in tests are not two deployed RC replicas. |
| Sustained saturation, queue growth, expiry/reclaim, retry/backoff and leaks | **UNVERIFIED.** Short executed deterministic tests provide no long-window observations. No production load or saturation series collected. |
| No duplicate physical work, including schedules and Goal reconciliation | **UNVERIFIED.** `scripts/soak/run_soak.py:1044-1077` cancels the schedule admission probe's queued Run explicitly without executing it. Admission identity checks cannot establish Attempt/effect uniqueness. |
| Rate/security/degraded non-bypass across replicas | **UNVERIFIED overall; replica allowance gap reproduced.** Both cases at `tests/test_soak_promotion_gates.py:439` passed using actual production middleware: the same identity gets `[200, 200, 429]` independently on both instances. `packages/maistro-server/src/maistro_server/api/rate_limit.py:32` documents the process-local aggregate allowance. |
| Required telemetry with explicit thresholds | **UNVERIFIED.** `scripts/soak/run_soak.py:1410-1423` measures driver loop lag, not application loop lag. No fresh complete production PostgreSQL, worker, queue, resource and error series exists from this round. |
| Kill/restart during active work with drain/fencing/recovery | **UNVERIFIED.** `scripts/soak/run_soak.py:1427-1450` signals by elapsed time without observing an active Attempt first. Rejoin and terminal Run totals alone do not prove physical recovery. |
| Long soak of unchanged exact RC artifact/config | **UNVERIFIED.** `scripts/soak/run_soak.py:730-742,1551` always rejects its host preflight as exact-RC evidence. Executed `test_four_hour_preflight_cannot_pass_cli` verifies missing/null/preflight artifact evidence fails even with synthetic four-hour duration. No immutable promotion RC/config was supplied. |
| Findings filed/reclassified before promotion | Local disposition recorded here; external filing/reclassification **UNVERIFIED**. No GitHub mutations permitted or performed. |
| Machine/human evidence tied to image/package/commit/config hashes | **UNVERIFIED for RC.** This source-validation report is bound to the starting HEAD, not deployed image/config hashes. It is not a promotion evidence pack. |

## Handoff

**BLOCKED on production acceptance.** The reported historical CI failure does not
reproduce, and the exact vulture ledger already matches. Editing the ledger or
changing passing tests would be speculative, not a repair. Only this report
changes; no source, test, gate, inventory, ledger or deployment configuration edits.
Full-tree pytest and live database integration were not run (six tests skipped).

Next requires a selected immutable RC/config, representative canonical-path
workloads, physical Attempt telemetry and resolution/disposition of the
replica-selection allowance gap; then execute a fresh long soak on that exact
unchanged deployment and publish hash-bound evidence. Repeating the same passing
CI repair cannot supply that evidence. Do not use this handoff as integration
approval or close #860.

Progress: checked 1 issue; acceptance-complete 0; skipped issues 0; fresh validation
errors 0. CI investigation done; production acceptance blocked. Commit locally.
