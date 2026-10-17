# Issue #860 — repair checkpoint (job 45da9863)

## Frozen scope

- Only issue #860; assigned worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Verified starting HEAD `38648fa0e0a1665fcf5f8b5cd6770daef1e61a5f`; supplied base `2154f845347c9541016288c760f8da3f5cd2e064` resolves locally.
- Initial worktree clean; no incoming edits to salvage. No merge conflict observed.
- Process the supplied dispatch snapshot only; no GitHub mutations or refreshes.
- Inspect existing soak harness/profile, promotion tests, adjacent changed production tests, relevant ADRs and supplied prior result/log. Run exact vulture scan before considering any permitted ledger repair. Edit scope: this checkpoint; production/test/ledger repairs only if actual validation identifies a defect within #860.
- Current job directory contains no `check-*.log` files at initial inspection. Writer role assumed from lane assignment; execute fresh validation rather than trusting historical claims.

## Progress

Fresh validation (1200-second timeout):

- Exact requested vulture command: PASS, 1323 reviewed identities / 1323 findings, zero unclassified or never-allowlist findings. No ledger change justified.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q`: PASS, 118 passed / 6 skipped in 2.59s.
- Supplied historical check-3.log was read: 24 schema DDL statements versus 21 expected. That failure does not reproduce in the current targeted suite. Skipped DB integration cases are not live production proof.
- Supplied previous result and checkpoint were read; their BLOCKED verdict was checked against current production paths, not treated as acceptance evidence.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3277 files already formatted.
- `uv run python scripts/check-doc-links.py`: PASS, 2704 Markdown files, no broken relative links.

## Architecture and reproduced evidence

Read repository AGENTS.md, accepted ADR-082826-b601 (canonical consumer), accepted ADR-085 (principal rate limits), and Proposed ADR-081 (deployment). ADR-081 is not an accepted waiver of the issue criteria. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`: admission uniqueness cannot substitute for physical-work fencing. No execution, event or authorization authority was added.

The historical schema failure already has its missing audit-column expectations at `packages/maistro-core/tests/persistence/test_pg_learnings.py:175–177`. Fresh tests exercise those expectations; changing production DDL or weakening this assertion would be unjustified.

The current production middleware constructs `InMemoryRateLimiter` per instance at `packages/maistro-server/src/maistro_server/api/rate_limit.py:94`. The executed regression `tests/test_soak_promotion_gates.py:439` observes 200/200/429 on each of two middleware instances for the same identity, for both authenticated and unauthenticated cases. This proves a component-level independent allowance, not a production topology experiment. ADR-085's principal identity requirement does not waive #860's replica-selection criterion. A shared-budget implementation is not a vulture/schema repair and must not be invented in this CI-only round.

`scripts/soak/run_soak.py:744–755` explicitly returns `ok: false` for exact RC identity: it boots host processes rather than the promoted Compose artifact. The executed four-hour preflight rejection regression at `tests/test_soak_promotion_gates.py:103` confirms that duration alone cannot pass promotion. No gate was relaxed.

## Acceptance matrix

| #860 criterion | Fresh evidence and remaining gap |
| --- | --- |
| Representative RC profile | **UNVERIFIED**. `m3a-load-profile.md` defines a preflight mix but explicitly lacks concurrent users/Workspaces, Graph fan-out, successful model/tool work, Design/Canvas and Goal/background workloads. No complete production profile validated. |
| Two application replicas | **UNVERIFIED** at production scale. Executed middleware-instance tests are not two deployed RC replicas. |
| Sustained saturation, queues, expiry/reclaim, retries, leaks and shutdown | **UNVERIFIED**. No sustained production workload executed this round. |
| No duplicate physical work across schedules/task/Run/Attempt and Goal reconciliation | **UNVERIFIED**. Profile's schedule probe admits then cancels a Run without executing it; that cannot prove physical execution fencing or sustained reconciliation. |
| Security/degraded behavior cannot be bypassed by replica selection | **UNVERIFIED** for deployment; executed production-middleware test positively demonstrates independent replica allowances. Local enforcement tests cannot establish cluster-wide enforcement. |
| PostgreSQL, application-loop, workers, RSS, descriptors, queues, errors/timeouts with thresholds | **UNVERIFIED**. Profile thresholds and sampler tests exist; no complete production observations. Driver event-loop lag is not application event-loop lag. |
| Kill/restart active work with drain/fencing/recovery | **UNVERIFIED**. No active-work production recovery experiment executed. |
| Long-running exact RC/config soak; repeat on changes | **UNVERIFIED**. Current harness fails exact-artifact gate by construction; no >=4-hour exact-RC run executed. Selecting/building an arbitrary image would not identify the artifact #89 intends to promote. |
| Findings filed/reclassified before promotion | **UNVERIFIED**. Limitations recorded locally; no new load experiment or remote filing. GitHub mutations prohibited. |
| Machine/human evidence bound to exact image/package/commit/config hashes | **UNVERIFIED**. This report binds local checks to the starting source commit, not a production image/config soak. |

## Disposition

**BLOCKED**: the supplied CI failure is not reproducible and the required ledger scan passes. No code, tests, inventory, ledger or grant changes are justified by these results. Only this checkpoint changed; no test-count delta, so no inventory note is needed.

The earlier acceptance block is not resolved. Next action is to designate the immutable RC/configuration, implement/use an exact-deployment runner with the representative workloads and missing application telemetry, reconcile replica-budget semantics, and execute the >=4-hour physical-work/recovery soak. Another rerun of the historical schema failure cannot supply that evidence. No remote actions taken.

Progress: checked 1 issue; acceptance-complete 0; skipped 0 issues; validation failures 0. This checkpoint is a local handoff, not integration approval.
