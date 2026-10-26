# Issue #860 — c840857e repair checkpoint

## Frozen scope

- Only issue #860; assigned worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD `ad27902d8c8edf9a835c04c95a21def8cfd2adaf`; supplied base `66f3cea9e98980f146a12cf3142d66e30986d276`.
- Initial worktree clean; no salvage necessary. Current job directory has no `check-*.log` files.
- Review inputs: supplied dispatch snapshot, prior result and specified prior check-3.log, repository instructions, relevant execution/soak ADRs, existing soak harness/tests/evidence, exact vulture gate and CI invocation.
- Planned write scope: this checkpoint; `quality/vulture-baseline.json` only if the actual scanner establishes retained unbanked identities. Production/test changes only if reproduced evidence warrants a focused #860 fix; document any such scope adjustment before editing.
- Ambiguity: dispatch says deterministic checks were run, but no current-job logs exist. Proceed by running validation locally; do not infer success from prior reports.

## Progress

Initial inspection confirms assigned HEAD and clean worktree. Prior result reports BLOCKED; its claims are inputs, not fresh validation. No integration or promotion approval is implied.

Fresh reproduction: `uv sync --locked --extra dev` passed. The exact requested vulture scan passed: 1,326 findings, 1,326 reviewed identities, zero unclassified/never-allowlist. No ledger amendment is justified. `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` passed (37 passed, 6 skipped). The supplied old check-3.log's 24-versus-21 DDL assertion failure does not reproduce. CI's vulture invocation matches the requested command. No speculative source/test repair will be made for either stale failure.

Focused validation: `uv run ruff check .` and `uv run ruff format --check .` passed (3,170 formatted files). `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q` passed: 100 tests. This freshly reproduces independent allowances on production limiter instances for the same authenticated and unauthenticated identity; it is not deployed soak evidence. `uv run python scripts/check-suite-inventory.py` passed: 17 suites, 29,499 unique identities, zero duplicates. No tests added/changed; no inventory delta required.

## Architecture and acceptance reconciliation

Read repository `AGENTS.md`, documentation authority map, accepted ADR-032, ADR-062 (including retired entry point), and ADR-081626-f383; deployment ADR-081 is Proposed, not an accepted waiver. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`. Fenced durable state and admission deduplication are not proof of exactly-once external physical effects. The lease ADR explicitly does not define expiry takeover. No scheduler, authorization path, event authority or Goal store was introduced.

`uv run python -` imported the current harness and evaluated unchanged historical `evidence/m3a-round30-shakedown.json`: 420.08 seconds, rejected for `sustain_duration` and `exact_rc_artifact`. Assertions confirming both rejections passed. The current runner returns `ok=false`, topology `host-uvicorn-preflight`. This is fresh evaluation of historical evidence, not a new soak. `uv run python scripts/check-merge-markers.py` and `git diff --check` passed. Validation commands used 1,200-second timeouts.

| Acceptance criterion | Fresh evidence / disposition |
| --- | --- |
| Representative RC workload profile | **UNVERIFIED.** `m3a-load-profile.md:153-172` explicitly lacks concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and Goal/background-worker workloads. Applicability for a selected RC remains unspecified. |
| At least two production replicas | **UNVERIFIED deployed.** Compose defines both at `deploy/docker-compose.prod.yml:26-77`; the executed ASGI tests do not boot that deployment. |
| Sustained saturation, growth, reclaim, retry/backoff and leak observations | **UNVERIFIED.** Historical 420.08-second preflight fails duration. Passing sampler tests prove observation mechanics, not sustained production observations. |
| No duplicate physical work across schedule/task/Run/Attempt/Goal paths | **UNVERIFIED.** `scripts/soak/run_soak.py:1045-1068` cancels the schedule probe's queued Run without physical execution. Receipt deduplication cannot prove effect uniqueness or recovery. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **UNMET for a shared principal budget.** Fresh `tests/test_soak_promotion_gates.py:439-488` cases obtain `[200,200,429]` independently on each production limiter instance, same credential/IP. `main.py:648` installs this middleware. `api/rate_limit.py:31-37` explicitly documents process-local scope; the local enforcement contract must not be misrepresented as cluster-wide protection. Broader deployed behavior remains **UNVERIFIED**. |
| Production telemetry and explicit thresholds | **UNVERIFIED.** Profile acknowledges driver loop lag is not application loop lag; sampler tests cannot establish worker census, pool saturation, query/lock contention or long-window leak/error bounds. |
| Active-work replica restart/drain/fencing/recovery | **UNVERIFIED.** Executed boot cleanup tests do not exercise physical work takeover or stale-effect rejection. |
| Long exact-RC artifact/configuration soak | **UNVERIFIED / blocked.** Fresh evaluator rejects historical evidence; current host runner always fails exact-RC identity (`run_soak.py:730-741`). No four-hour production run executed. |
| Findings filed/reclassified before promotion | **UNVERIFIED completeness.** Existing historical findings are not a complete current workload disposition. No GitHub mutation performed. |
| Machine/human evidence bound to exact image/package/commit/config | **UNVERIFIED for candidate.** Historical evidence is preserved unchanged, not relabeled for this HEAD. No immutable RC image/config selection is supplied by this lane. |

## Handoff

Verdict **BLOCKED**. Only this report changed; no source, tests, inventory, gates or ledger amendments were justified by fresh reproduction. The supplied schema failure is already repaired (test now enumerates the three audit columns at `test_pg_learnings.py:173-177`); the exact debt ledger matches its scanner. Repeating this CI-repair dispatch will not resolve production acceptance.

Required next inputs/work: select the immutable RC images and normalized configuration with a working model gateway; complete the representative workload/telemetry plan; resolve the replica-selection budget contract through the existing limiter/auth seam; execute at least four hours on the exact RC with active physical-work recovery/fencing observations and hash-bound evidence. Do not substitute a longer host-process preflight or invent a second execution authority. This round does not claim to resolve those prerequisites.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: "production RC selection and acceptance execution; no remaining reproduced CI repair"}`. Focused validation complete, issue completion not claimed. Report is committed locally before handoff; no push, PR, merge or issue action.
