# Issue #860 — repair checkpoint 099833e8

## Frozen scope

- Sole item: issue #860 on `auto-860`, starting at
  `f7f02f094139d3ffd3cff5992d2cd32f631875dd`, supplied base
  `ac7370141e8e61bd6f352bca35ed0b505104aadb`.
- Worktree was clean. No salvage needed; no remote mutation or sync conflict.
- Repair candidates: `packages/maistro-core/tests/persistence/test_pg_learnings.py`,
  `packages/maistro-core/src/maistro/persistence/pg_learnings.py`, and
  `quality/vulture-baseline.json` only if the required scan identifies reviewed debt.
- Validation/read scope: supplied dispatch context and prior results, repository
  instructions/ADRs, `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, adjacent persistence tests and schema,
  production API/rate-limit/receipt wiring, relevant quality-gate scripts/workflows,
  `docs/testing/soak/m3a-load-profile.md`, and
  `docs/testing/soak/m3a-soak-evidence.md`.
- Documentation changes: this checkpoint and a matching inventory note if tests change.
  No other issues or PRs will be processed.

## Initial evidence and assumptions

- Supplied prior `check-3.log` reports 24 observed DDL statements versus 21 expected
  in the schema-fence test. This historical result must be reproduced on this head.
- The current job directory contains no driver `check-*.log` files at initial inspection.
- Supplied prior result is BLOCKED, not a claim of acceptance.
- Assumption: this is a writer CI-repair round; the explicit ledger exception applies
  only to actual Vulture findings. A clean scan requires no ledger amendment.

## Validation

Fresh commands (1,200-second timeout each):

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS; 1,322 reviewed identities and 1,322 findings, zero unclassified/never-allowlist. Matches workflow arguments. No ledger amendment justified.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`: PASS; 37 passed, 6 skipped. The historical 24-versus-21 DDL failure does not reproduce: the test already includes the three validation audit columns.

The issue body was extracted from the supplied offline dispatch snapshot. No
remote re-fetch occurred. Its ten acceptance criteria require production soak
proof, not merely passing these checks. Additional focused validation:

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS; 3,301 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: PASS; 73 tests in 2.27 seconds.
- All commands above used a 1,200-second timeout. No test additions, removals,
  source changes, or inventory deltas are warranted. Six persistence tests were
  skipped; this is not live PostgreSQL validation.

## Architecture and evidence reconciliation

Read repository `AGENTS.md`, documentation authority map, accepted
ADR-081426-1f7c (ExecutionRuntime) and ADR-081626-f383 (lease/fencing), and the
profile's cited ADR-081. ADR-081 is **Proposed**, not an accepted deployment
contract. The runtime owns mechanics for canonical Attempts, not domain state.
Accepted fencing ADR explicitly leaves live-Attempt expiry takeover undefined;
#860 cannot authorize inventing reclaim semantics or a second execution authority.
Preserve Goal -> Graph -> Run -> NodeRun -> Attempt.

The current code/tests, not historical pass claims, establish these narrow facts:

- `packages/maistro-core/src/maistro/persistence/pg_learnings.py:215` takes the
  transaction-scoped advisory lock before schema updates. The ordered test list
  already includes audit columns at `test_pg_learnings.py:176`.
- `scripts/soak/run_soak.py:744` returns `ok: false` for exact-RC equivalence.
  Executed CLI tests reject missing, null and host-preflight artifact evidence
  even at a synthetic four-hour duration. This is a gate test, not four hours
  of production traffic.
- `tests/test_soak_promotion_gates.py:439` exercises real production middleware:
  the same authenticated or unauthenticated identity receives `[200, 200, 429]`
  independently from both instances. `api/rate_limit.py:32` documents process-local
  budgets. Six-path overload rejection does not prove a shared budget.
- `tests/test_soak_promotion_gates.py:564` exercises the production task router
  with canonical admission and separate queues: local receipt 200, peer 404.
  `packages/maistro-server/src/maistro_server/api/tasks.py:144` reads the local queue.
- Read `m3a-load-profile.md` and `m3a-soak-evidence.md`. Historical preflight
  evidence is explicitly provisional, and cannot be promoted to a new exact-RC
  soak by rerunning unit tests or extending the emulator's duration.

## Acceptance matrix (all ten issue criteria)

| Criterion | Executed evidence or remaining status |
| --- | --- |
| Representative RC load profile | UNVERIFIED. Existing profile omits concurrent users/Workspaces, graph fan-out, successful model/tool calls and Design/Canvas/Goal traffic without an RC-specific applicability decision. |
| At least two production replicas | UNVERIFIED. Fresh tests used ASGI instances, not deployed application replicas. |
| Sustained saturation, growth, expiry/reclaim, retries, leaks | UNVERIFIED. No sustained production run performed; accepted ADR constrains reclaim semantics. |
| No duplicate physical work, admission and Goal reconciliation | UNVERIFIED. Probe-oracle tests are not physical Attempt execution or Goal reconciliation evidence. |
| Replica-resistant security and degraded behavior | UNVERIFIED overall; fresh middleware tests reproduce independent allowances, and backpressure tests pass. These do not prove replica-selection non-bypass. |
| Production telemetry with explicit thresholds | UNVERIFIED. The live child-process sampler test passes, but no new production PG/lock, application-loop, queue/error or leak time series exists. |
| Kill/restart during active work with drain/fencing/recovery | UNVERIFIED. Cleanup tests are not an active-work deployment failure/recovery run. |
| Long-running exact RC artifact/configuration soak | UNVERIFIED. Current runner explicitly fails exact-artifact proof; CLI tests confirm the rejection. |
| Findings classified to earliest broken milestone | UNVERIFIED for completeness absent production load. Historical classification is not revalidated by unit tests; no GitHub mutations allowed. |
| Machine/human evidence bound to image/package/commit/config hashes | UNVERIFIED for promotion. This report identifies tested source; it does not supply fresh immutable production artifact/configuration evidence. |

## Handoff

Verdict: **BLOCKED**. The specific historical CI failure is already repaired on
this starting head, and the mandated Vulture scan is clean. No speculative
repair or ledger banking was performed. Only this handoff changes.

Next: designate the immutable RC and effective configuration; provide an
exact-artifact workload/telemetry runner; reconcile independent replica allowances,
receipt visibility and reclaim-contract limits; execute the representative long
soak with active-work recovery and physical-work observations. Repeating this
same CI-only lane cannot satisfy those production acceptance criteria.

Progress: checked 1 issue; done 0 complete acceptance sets; skipped 0 issues;
errors 0 validation commands. No integration or issue-closure approval implied.
Final `git diff --check` passed. `git diff --exit-code --` for both schema
source/test files and the Vulture ledger passed (unchanged). `git status --short`
showed only this new report before staging. Handoff committed locally; no push.
