# #2406 focused repair snapshot

Starting head: `1eb2d8868b5ff25abff8f2aaba9245c0021711e3`.
Assigned item: #2406 only. Frozen evidence: dispatch-context.json and check-0.log through check-5.log in job `08bb21d9c27a41b5a8ffdc40e6283851`, plus supplied prior result.

Scope: investigate recorded diff-coverage misses in Canvas PgCanvasStore.get_blob and server canvas_runtime; add meaningful tests/inventory notes where justified; run exact vulture repair gate and focused validation. No remote mutations, no unrelated gate changes, no grant edits.

Initial salvage: `git log --oneline -20`, `git diff --stat`, `git status --short` show clean starting tree. The alleged preserved develop conflict is absent: merges f721ec08d6 and dec3c68286 already record resolution through assigned base 228dec753f. Assumption: no new develop sync is needed in this frozen-head repair (no conflict exists to resolve). Prior attempts stopped with uncovered branches and unverified external gates; preserve all existing implementation.

Evidence checkpoint: supplied check-0..5 logs show dependency sync, Ruff, 136 focused tests and both suite inventories passing. Prior result explicitly reproduces missing diff coverage (get_blob 20%, canvas_runtime 83%); current tests stub the fetch entirely and only test cooperative shutdown. Plan: exercise actual HTTP parsing/failure via transport, cancellation/abandonment/outcome paths via event-controlled tasks, and durable blob roundtrip/missing id using the existing PostgreSQL fixture. ADR-044 requires preserving persisted legacy state until bridge/backfill; ADR-045 allows the transitional routes and forbids competing execution authority. No production redesign is justified. Exact vulture scan executed successfully: 1222 findings, zero unbanked/stale; no ledger amendment is warranted. Base ancestry check succeeded. Docker is available; use a dedicated repair PostgreSQL service for migration-backed blob assertions. The existing migration roundtrip already writes a blob but never reads it, so extend that test rather than duplicate the fixture/schema.

Implementation checkpoint: added 16 server cases for real HTTP fetch/fail-closed parsing and event-controlled shutdown; corrected existing idempotence test to call shutdown twice; extended migration-backed blob roundtrip with actual read/missing-id assertions; added inventory note; corrected the unsupported alternate-token claim in prior bring-up notes. Focused runtime tests: 33 passed. Dedicated pgvector/pg18 service `cr2406-repair-pg` on 55406 started successfully; full Canvas suite with required PostgreSQL legs under branch coverage: 628 passed, 3 skipped (41.15s).

Validation checkpoint: full server suite under branch coverage: 697 passed, 10 skipped (66.83s). Combined Canvas/server diff-coverage now has no below-floor measured files; the gate fails only because the core settings source producer has not yet run (explicit missing measurement, not a code failure). Full Ruff found B904 in the new deliberately cancellation-resistant fake; fixed exception chaining with `raise error from None`. Formatting passed.

Gate checkpoint: core production-registration suite 14 passed under the core coverage source; combined diff-coverage now passes all 10 measured changed files at 90% lines/80% arcs against exact base 228dec753f. Reachability (1494 modules/82 unreachable), dispositions (27 groups), convergence (52 subsystems), suite inventory (631 Canvas/707 server; delta +16 server), full Ruff and format all passed. Radon output names 124 current blocks and zero new/regressed findings; record individual subprocess status in the final gate log before claiming its result. The source issue #2311 boundary explicitly leaves Attempt convergence to #735; retained legacy routes are reconciled with accepted ADR-044's migration/backfill requirements, not claimed deleted.

Final evidence checkpoint: radon, ratchet-provenance (55 consumers), durable-table inventory (124 tables), and shipped-surface-truth each returned 0 (individual return codes captured in `/tmp/cr2406-final-gates.log`). Exact changed-line coverage: store.py 5/5; canvas_runtime.py 141/141 with 24/24 branch arcs. Three source-free mutation probes each exited 1 at the intended assertion: no gateway fetch -> zero requests; omitted task cancellation -> interruption event unset; blob reader always None -> persisted byte assertion fails. `git diff --check` passes. No production/ledger/grant changes were made.

Residual documentation evidence: docker-compose.yml:81-82 and .env.example:94 also advertise X-Canvas-Token as an alternative without explaining that default REQUIRE_AUTH rejects requests lacking Authorization first. Prior bring-up note is corrected here; deployment credential documentation needs an auth-owner review rather than guessed credential instructions. AC5 full default-compose live bring-up was not re-run this round: only dedicated PostgreSQL plus production router/lifespan tests were executed. Publish-set aggregate, full CI/security/supply-chain/mutation/formal gates remain UNVERIFIED by this repair.

Remote PR-body closure/stale evidence cannot be edited under the no-GitHub-mutations rule. Inert grants likewise remain outside the explicitly permitted vulture-ledger exception. Record these for integrator rather than broadening scope.

## Executed validation commands

All `uv run` invocations used the existing locked dev environment. Long command
timeouts were 1000–1800 seconds; suite pytest used CI's `--timeout=30`.

- `uv run pytest packages/maistro-server/tests/api/test_canvas_runtime.py -x -q --timeout=30`: 33 passed.
- `MAISTRO_TEST_PG_DSN=postgresql://maistro:maistro@127.0.0.1:55406/maistro_test MAISTRO_REQUIRE_PG_LEGS=1 COVERAGE_FILE=.coverage.cr2406-repair uv run coverage run --branch --source=packages/maistro-canvas/src/maistro_canvas -m pytest packages/maistro-canvas/tests -x -q --timeout=30`: 628 passed, 3 skipped.
- `COVERAGE_FILE=.coverage.cr2406-repair uv run coverage run --append --branch --source=packages/maistro-server/src/maistro_server -m pytest packages/maistro-server/tests -x -q --timeout=30`: 697 passed, 10 skipped.
- `COVERAGE_FILE=.coverage.cr2406-repair uv run coverage run --append --branch --source=packages/maistro-core/src/maistro -m pytest packages/maistro-core/tests/graph/nodes/test_production_registration_universe.py -x -q --timeout=30`: 14 passed.
- `COVERAGE_FILE=.coverage.cr2406-repair uv run coverage xml -o /tmp/cr2406-coverage.xml`, then `uv run python scripts/check-diff-coverage.py /tmp/cr2406-coverage.xml --base 228dec753f42e96819f4c95d8becdfa55ff6b427`: passed after the core source producer. This is focused diff evidence, NOT a publish-set aggregate measurement.
- `uv run ruff check .`, `uv run ruff format --check .`: passed after the documented B904 repair.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: passed, 1222 findings, no ledger change required.
- `uv run python scripts/check-{reachability,reachability-dispositions,convergence-matrix,radon-baseline,ratchet-provenance,durable-table-inventory,shipped-surface-truth}.py` (each separately, no literal brace argument): passed.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-canvas/tests --suite packages/maistro-server/tests`: passed, 631/707 collected.
- Three isolated `uv run python` / `pytest.main` mutation probes: each intentionally failed at the corresponding new behavioral assertion (exit 1); no source modified.
- `git diff --check`: passed.

## Acceptance and handoff

1. Cutover/RETIRE: parity tests pass in full Canvas suite; `/v2/canvas` asset
   mount and explicit transitional legacy markers retained. Full legacy-route
   deletion is NOT proven or claimed: accepted ADR-044 requires bridge/backfill
   first, so this repair preserves prior reconciliation.
2. Runner start: production lifecycle/composition tests pass in full server
   suite, including durable-spine/store start, skip/opt-out, restart and bounded
   shutdown. Default-compose live liveness is UNVERIFIED this round; no second
   execution authority added. #735 still owns Attempt convergence.
3. Design registration: 14 production-registration-universe tests pass.
4. Dispositions/reachability: all three reachability/disposition/convergence
   gates pass; exact vulture and provenance gates pass unchanged.
5. Default-compose `/v2/canvas`: production route tests pass and root-migration
   store tests pass against PostgreSQL 18. Full-stack live bring-up UNVERIFIED
   this round; do not substitute prior claims for current execution.

Next/integrator: correct captured PR-body premature `Closes #2311` and stale
counts/debt prose; review credential docs and the two inert grants at
quality/ratchet-authorizations.json:588,593 under appropriate authorization;
run complete CI and live default composition. No remote mutation performed.
Progress: checked 1 assigned item, repaired 1 local coverage defect, skipped 0,
remaining integration/acceptance evidence explicitly listed above. Local commit
is handoff only, not issue closure, deployment, or integration approval.
