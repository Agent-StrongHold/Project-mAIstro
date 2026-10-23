# Issue #860 — repair round 53796e4b

## Frozen scope

- Assigned issue: #860 only; branch `auto-860` in the assigned worktree.
- Starting HEAD: `661e6c6dd0395a479384c7f5471f00f976f1f7fb` (resolved); supplied base: `3c761d14db944a727fa0744444bc67cfe36d49f7` (resolved by diff).
- Worktree initially clean; no incoming edits to salvage.
- Process the supplied dispatch snapshot and prior result only; no GitHub mutations or list refreshes.
- Candidate edits: this report, and `quality/vulture-baseline.json` only if the required scan supplies reviewed identity evidence. No speculative production changes.
- Read-only validation scope: repository instructions, relevant ADRs, soak runner and adjacent tests, vulture checker/CI configuration, and supplied evidence.

## Initial observations

The supplied job directory has no `check-*.log` files at initial inspection. The prior result reports BLOCKED, not acceptance. Its claims will not substitute for current executed checks.

Assumption: this is the writer/CI-repair lane, not a read-only verifier lane. The explicit writer assignment and commit requirement control. No exact deployed RC artifact or configuration is designated in the assignment; do not invent one or relabel host-process evidence as production evidence.

## Executed checkpoint

- Required exact vulture scan passed: 1323 findings / 1323 reviewed identities, zero unclassified. No ledger amendment is warranted by evidence.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q -rs` passed: 37 passed, 6 skipped (no migrated PostgreSQL DSN), 1.47s.
- Read the supplied historical `98a11313.../check-3.log`: failure was 24 actual schema statements versus 21 expected. It does not reproduce at the assigned HEAD.
- Commands ran with 1200-second timeouts.
- `uv run ruff check .` passed; `uv run ruff format --check .` passed (3270 files).
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q -rs` passed: 74 passed in 2.36s. This includes the real middleware replica-allowance counterexample, not deployed RC validation.
- `uv run python scripts/check-suite-inventory.py` passed: 17 suites, 31128 unique identities. No tests added, so no inventory delta required.
- `uv run python scripts/check-deployment-claims.py` passed (static existence validation only).

## Architecture

Read repository AGENTS.md, docs/README.md, accepted ADR-073126-c4e1 (release), ADR-085 (principal-keyed rate limits), and ADR-082526-b36a (renewable leases and fencing). Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`. A restart alone cannot establish worker death; a host-process preflight cannot establish exact RC provenance. Process-local rate enforcement does not waive the issue's replica-selection non-bypass requirement. No competing execution or authorization authority introduced.

## Acceptance audit

| Issue criterion | Current evidence and disposition |
| --- | --- |
| Representative RC profile | **UNVERIFIED.** Runner lines 1373–1395 use one credential and health/task/receipt/metrics traffic. `m3a-load-profile.md:152` records absent multi-user/Workspace, Graph fan-out, successful tools/models, Design/Canvas and Goal/background-worker workloads. |
| At least two deployed application replicas | **UNVERIFIED.** Executed ASGI middleware tests cover two instances, not two deployed RC containers. No live stack started this round. |
| Sustained saturation, growth, reclaim, retries, leaks and restart | **UNVERIFIED.** Sampler tests exercise real wrapper/child resource growth; sustained accounting tests are bounded fixtures, not a sustained deployment. |
| Physical-work uniqueness across replicas | **UNVERIFIED.** `scripts/soak/run_soak.py:1044–1068` explicitly cancels the schedule probe's unexecuted Run. Admission uniqueness cannot establish physical-effect fencing. |
| Rate/security/degraded non-bypass | **UNVERIFIED overall; replica allowance increase reproduced.** `tests/test_soak_promotion_gates.py:439` exercises production middleware for authenticated and pre-auth identities. Each instance accepts two requests then returns 429 independently. `api/rate_limit.py:93` constructs the process-local limiter. The passed task backpressure test proves a narrower admission/recovery property, not cluster-wide non-bypass. |
| Required telemetry and thresholds | **UNVERIFIED at RC level.** Sampler tests pass; `scripts/soak/run_soak.py:1410–1422` measures driver-loop lag, not application-loop latency. No current deployed time series or complete RC thresholds validated. |
| Active-work kill/restart, drain/fencing/recovery | **UNVERIFIED.** Drain/promotion unit checks pass, but no live fault injection or physical-effect oracle executed. |
| Long unchanged exact-RC soak | **BLOCKED / UNVERIFIED.** No designated immutable promotion artifact/configuration in the assignment. `scripts/soak/run_soak.py:730–741` rejects host preflight as exact RC; executed synthetic four-hour tests prove rejection, not four hours of deployed traffic. |
| Findings filed/reclassified | Local findings recorded here. External filing/reclassification **UNVERIFIED**; GitHub mutations prohibited. No stale scanner/test failure presented as newly reproduced. |
| Machine/human evidence bound to image/package/commit/config hashes | **UNVERIFIED.** This source-linked validation report is not a deployed RC evidence pack. |

## Final validation and disposition

- Workflow's exact vulture arguments confirmed at `.github/workflows/vulture-ratchet.yml:82`.
- `uv run python scripts/check-ratchet-provenance.py` passed (53 consumers); two SyntaxWarnings from scanned strings, no failure.
- `uv run python scripts/check-shipped-surface-truth.py` passed.
- `git diff --check` passed before final report update; rerun at commit.
- Historical schema mismatch is already addressed by audit-column expectations at `packages/maistro-core/tests/persistence/test_pg_learnings.py:176–178`.

**BLOCKED**, not integration approval. Only this report changed. No source/test/ledger repair is supported by the supplied stale failure or current scanner output; all inherited work is preserved. No tests added, inventory unchanged. Six PostgreSQL integration cases skipped without a migrated DSN. Existing production workload/recovery/telemetry gaps are not waived.

Next: release owner designates immutable RC artifact/configuration and applicable workload surfaces; complete deployed workload, physical-effect/recovery oracle and application telemetry; resolve replica-budget semantics through the existing authority; execute the unchanged >=14400-second multi-replica soak and publish hash-bound evidence. Another schema/vulture rerun cannot discharge these acceptance criteria. Do not treat this validation-only commit as an implementation fix.

Progress: checked 1 issue; acceptance-complete 0; skipped issues 0; failed validation commands 0. Commit this checkpoint locally; no push, merge, PR, comment or closure action.

