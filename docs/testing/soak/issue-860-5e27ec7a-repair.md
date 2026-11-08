# Issue #860 repair — job 5e27ec7a

## Frozen scope

- Only issue #860, branch `auto-860`, starting head `a087f28952362c8cd7df875697055695214243be`, base `66f3cea9e98980f146a12cf3142d66e30986d276`.
- Initial worktree clean. No salvage needed. No GitHub mutations.
- Inspect supplied dispatch snapshot, prior result and failed check; no remote enumeration.
- Candidate repair files: `packages/maistro-core/tests/persistence/test_pg_learnings.py`, its production `pg_learnings.py`, `quality/vulture-baseline.json` only if the exact scanner supplies actionable evidence, matching inventory note if tests change, and this report.
- Acceptance inspection only: `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`, `docs/testing/soak/m3a-load-profile.md`, existing soak evidence, relevant ADRs and CI gate definitions.

## Initial evidence and assumptions

Current job contains no `check-*.log`. Supplied prior `98a11313167b41a98a420abfda80c292/check-3.log` failed the schema-fence ordered DDL count (24 actual versus 21 expected). Prior result `c840857e4eef42ba9ca630e9b568fba8/result.json` reports BLOCKED acceptance, not a merge conflict. Neither claim is treated as fresh validation. Assumption: reproduce first; do not change passing code or manufacture ledger debt. Exact promoted RC identity/configuration is not supplied in the lane brief; host preflight cannot substitute for it.

## Results

- `uv sync --locked --extra dev`: passed (207 packages checked).
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`: **37 passed, 6 skipped**. The prior 24-versus-21 failure does not reproduce: the starting test already includes all three Gauntlet columns independently of production constants. Skipped PostgreSQL tests are not live concurrency evidence.
- Exact required `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: **passed**, 1326 reviewed identities / 1326 findings, zero unclassified or never-allowlist. No ledger amendment is justified.
- Read accepted runtime, lease/fencing and release ADRs. Reconciliation: a Run admission race does not establish physical Attempt uniqueness; a host preflight is not the immutable RC promoted by the release process. Preserve canonical authority; no replacement scheduler, store or authorization path.

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3170 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q`: **100 passed**. These include real production limiter instances, HTTP probe accounting and a real child-process resource sampler, but are not a deployed soak.
- `uv run python scripts/check-suite-inventory.py`: passed, 17 suites, 29,499 unique identities, no duplicate evidence. No tests changed or added; no inventory delta needed.
- `uv run python scripts/check-merge-markers.py`: passed.
- Read ADR-082526-b36a as well: it adds expiry/renewal/reclaim to the earlier fencing contract, including transient renewal-failure handling. The earlier ADR's historical boundary must not be used to claim reclamation is undefined today. Its canonical mechanism still needs observation under the requested deployment load.

- `uv run python -` imported the current soak harness and evaluated unchanged `evidence/m3a-round30-shakedown.json`: **420.08 seconds**, rejected for **sustain_duration** and **exact_rc_artifact**. Assertions checking both rejections passed. Current `preflight_artifact_check()` returns `ok=False`, topology `host-uvicorn-preflight`. This is fresh evaluation, not fresh soak execution.
- Latest three captured issue comments contain progress/blocker reports, not a selected RC artifact. No remote request was made.

No reproduced CI defect remains in this snapshot. All validation commands used 1,200-second timeouts. Historical evidence remains unchanged.

## Acceptance disposition

| # | Criterion | Fresh evidence / remaining gap |
| --- | --- | --- |
| 1 | Representative RC workload | **UNVERIFIED.** `m3a-load-profile.md:153-172` records missing concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and Goal/background-worker work. Applicability needs the selected RC config. |
| 2 | Two deployed application replicas | **UNVERIFIED live.** `deploy/docker-compose.prod.yml:26-77` defines two replicas, but executed ASGI tests do not deploy them. |
| 3 | Sustained saturation, queue growth, reclaim, retry/backoff, leak and restart observations | **UNVERIFIED.** The historical 420.08-second preflight is below the 14,400-second minimum. Sampler tests establish measurement mechanics, not long-window production behavior. |
| 4 | No duplicate physical work across schedule/task/Run/Attempt/Goal paths | **UNVERIFIED.** `run_soak.py:1044-1068` cancels the schedule race's queued Run without executing it. Receipt/admission deduplication alone cannot prove physical effects or Goal reconciliation. |
| 5 | Rate/security/degraded behavior cannot be bypassed by replica selection | **UNMET for a shared principal budget; broader deployed security UNVERIFIED.** Executed `test_soak_promotion_gates.py:439-488` observes `[200,200,429]` on each independent production limiter for the same authenticated and unauthenticated identity. Production installs it at `main.py:648`; `api/rate_limit.py:31-37` documents the N-times-local allowance. Do not relabel local enforcement as cluster-wide protection or introduce a parallel auth path. |
| 6 | Production telemetry and explicit pass/fail thresholds | **UNVERIFIED complete.** Profile has thresholds, but driver-loop lag is not application-loop lag; no new production saturation, query latency/lock contention, worker census, leak/error series was collected. |
| 7 | Kill/restart during active work proves drain/fencing/recovery | **UNVERIFIED.** Passing boot cleanup and probe tests do not observe physical work takeover and stale-effect rejection. |
| 8 | Long soak on the exact promoted RC/configuration | **UNVERIFIED / blocked.** Historical evidence freshly fails both duration and artifact checks. `run_soak.py:730-741` explicitly rejects the host-process topology; no exact-RC four-hour run was executed. |
| 9 | Findings filed/reclassified before promotion | **UNVERIFIED completeness.** No new load observations; historical reports cannot prove all current findings are classified. GitHub mutations are prohibited and were not performed. |
| 10 | Machine/human evidence bound to exact image/package/commit/config hashes | **UNVERIFIED for candidate.** Preserved historical files are not evidence for this HEAD. No immutable promoted image/configuration selection is established by the inspected brief and evidence. |

## Handoff

**BLOCKED**, not integration approval. Changed only this report; production, tests, inventory and ledgers require no speculative changes. The supplied schema-count failure is already repaired at `test_pg_learnings.py:173-177`, and the exact vulture scan passes. Repeating the same CI-repair request cannot satisfy #860.

Next: select the immutable RC artifact/configuration and working model gateway; finish representative workload and production telemetry coverage; resolve the replica-selection budget acceptance through the existing security seam; execute at least four hours with active-work recovery/fencing and hash-bound evidence. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`; do not substitute a longer host preflight or new execution authority. No live database concurrency validation or production soak is claimed in this round.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "selected RC and production acceptance execution"}`. This report is committed locally for handoff; no push, PR, merge or issue action.
