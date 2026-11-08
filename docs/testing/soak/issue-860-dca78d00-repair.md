# Issue #860 repair — dca78d00

## Frozen scope

- Sole item: issue #860, assigned worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD: `ef2ad985a02127ceeb1876a3f43846fbd6b5acc3`; supplied base: `2154f845347c9541016288c760f8da3f5cd2e064` (both resolve).
- Initial worktree is clean; no uncommitted salvage required.
- Evidence snapshot: supplied dispatch-context.json, prior result 14368c06, and prior check-0 through check-3 logs from job 98a11313. Current job has no check logs at initial inspection.
- Processing files: repository instructions/ADRs, `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`, soak profile/evidence docs, vulture checker/workflow and `quality/vulture-baseline.json` if the required scan proves a discrepancy. Only this report and evidence-backed fixes in that scope will be committed.
- Ambiguity: task contains verifier and writer instructions; explicit assigned repair and writer commit requirement select writer mode. No GitHub mutations or speculative develop merge.

## Initial evidence

Prior result reports BLOCKED, not promotion readiness. Large inherited branch/base divergence is not authorization to edit unrelated files. Acceptance and prior scanner claims will be checked independently.

## Results

Required exact vulture scan passed: 1323 reviewed identities / 1323 findings, zero unclassified or never-allowlisted findings. No ledger discrepancy exists to amend. Prior check-3.log is instead a learning-schema test failure (24 DDL statements vs 21 expected), to be reproduced against current code. Read the complete issue acceptance body and captured linked PR bodies; none supplies current exact-RC acceptance evidence. Accepted ADR-081226-a66b, ADR-081626-f383 and ADR-085 preserve canonical lifecycle/fencing and principal rate policy. In particular, implicit lease-expiry takeover is not authorized by the fencing ADR. The load profile explicitly marks missing representative workload classes and host-process topology as promotion blockers.

Fresh targeted tests passed: 117 passed / 6 skipped for learning schema, soak promotion gates and production boot contract; 27 passed for server rate-limit and task concurrency backpressure tests. The historical 24-vs-21 failure is already repaired: current expectations include all three Gauntlet audit columns. The six skipped database tests are not live validation. Two real middleware instances still independently return [200, 200, 429] for the same identity, both authenticated and unauthenticated (`tests/test_soak_promotion_gates.py:439`). The runner cancels schedule probes without physical execution (`scripts/soak/run_soak.py:1067`) and deliberately rejects its topology as exact-RC evidence (`:744`). No source or test repair is justified by the supplied old failure or clean scanner.

## Commands and outcomes

All commands ran in the assigned worktree with 1200-second validation timeouts.

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1323/1323 identities. Ledger unchanged.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q`: PASS, 117 passed, 6 skipped.
- `uv run pytest packages/maistro-server/tests/api/test_rate_limit.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: PASS, 27 passed.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3277 files already formatted.
- `uv run python scripts/check-backlog-consistency.py`: PASS, 168 items.
- `uv run python scripts/check-adr-index.py`: PASS.
- `uv run python` evaluator probe using `runpy.run_path('scripts/soak/run_soak.py')`: PASS assertions that the current artifact check is false and historical `docs/testing/soak/evidence/m3a-round6-shakedown.json` fails both `sustain_duration` and `exact_rc_artifact`. This is a freshly executed rejection check, not a new load run.

Supplied prior check-0/1/2 logs record dependency, lint and formatting successes. Prior check-3 is the schema regression reproduced above as now passing. No current driver check logs were present at start; none is represented as newly executed by this worker.

## Acceptance audit

| Issue criterion | Current evidence / disposition |
| --- | --- |
| Representative RC load profile | `m3a-load-profile.md` explicitly omits multi-user/Workspace populations, Graph fan-out, successful tool/model calls, Design/Canvas and Goal/background-worker reconciliation. Complete representative RC profile UNVERIFIED. |
| At least two deployed application replicas | Two production middleware instances exercised in ASGI tests, not two deployed RC replicas. UNVERIFIED. |
| Sustained saturation, queues, expiry/reclaim, retries and leaks | No new sustained load run. Historical short evidence rejected by the evaluator. UNVERIFIED. |
| No duplicate physical work, including Goal reconciliation | Admission gate tests pass; schedule probe cancels its Run without physical execution at `run_soak.py:1067`. Physical uniqueness and Goal reconciliation UNVERIFIED. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | `test_replica_selection_has_an_independent_production_allowance` passes for both identity classes by reproducing an independent [200, 200, 429] allowance on each instance. `main.py:648` installs that middleware; `api/rate_limit.py:93` allocates a limiter per instance. Aggregate non-bypass NOT MET; full deployed security/degraded behavior UNVERIFIED. |
| PostgreSQL/application-loop/process/RSS/fd/queue/error telemetry and thresholds | Profile describes partial telemetry; driver-loop lag is not application-loop lag. No fresh RC telemetry. UNVERIFIED. |
| Kill/restart during active work, graceful drain/fencing/recovery | Unit gate checks cannot demonstrate physical recovery; no new active-work restart. UNVERIFIED. |
| Long-running exact RC artifact/configuration soak | Current artifact gate returns false, even for long host-process runs. No identified exact-RC deployment exercised for >=4 hours. UNVERIFIED. |
| Findings filed/reclassified to earliest broken invariant | Local backlog consistency passes, but complete production findings/classification UNVERIFIED. No GitHub mutation performed. |
| Publish machine/human evidence tied to exact hashes | This report records local validation only, not a new hash-bound production soak pack. UNVERIFIED. |

## Disposition

**BLOCKED** on production acceptance, not vulture or the historical schema test. The prior BLOCKED result is confirmed by fresh validation and cannot be resolved by a speculative ledger amendment or changing promotion gates. Only this report changed; no tests were added or removed, so no inventory delta is required. No execution, event, authorization or Goal authority changed. ADR-081 is Proposed, not an acceptance waiver; accepted ADR-081626-f383 does not authorize inventing implicit lease takeover to satisfy the issue.

Required next work: identify the exact RC image/config manifest and representative supported workloads, resolve the process-local versus aggregate non-bypass policy, implement physical-effect/recovery observations through the existing canonical spine, and execute the >=4-hour production soak with hash-bound telemetry. Another clean vulture scan cannot supply that evidence.

Progress: checked 1 issue; acceptance-complete 0; skipped 0; failed validation commands 0; blocked 1. This local commit is a handoff only, not integration approval. Residual risks are every unverified production acceptance surface above and the inherited branch/base divergence, which this bounded repair did not alter.
