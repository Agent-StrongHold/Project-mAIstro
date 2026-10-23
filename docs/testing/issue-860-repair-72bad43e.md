# Issue #860 bounded repair — 72bad43e

## Frozen scope

- Assigned item: #860 only; branch `auto-860`.
- Starting HEAD: `b9d99b13c48dbc34275068b163efce16be7b58c4` (verified); base supplied: `ab8b3737fa64f8d840f421ef87ca506c509444ff`.
- Initial worktree clean; no salvage needed.
- Inputs: supplied dispatch-context.json, prior result c976773f, prior check-3.log from 98a11313, repository instructions/ADRs, existing soak implementation and adjacent tests.
- Edit scope: this report and, only if the requested exact vulture scan demonstrates retained/unbanked identities, `quality/vulture-baseline.json`. Any necessary code repair must be supported by that scan, not speculative cleanup.
- No GitHub mutations, ref refreshes, scheduling/auth authority changes, or production promotion.

## Initial evidence and assumptions

The job directory has no driver `check-*.log` files. The prior result reports BLOCKED with all ten production acceptance criteria unverified. This round will independently reproduce the specified gate and run focused acceptance tests, not infer readiness from that result.

The assignment is a writer CI-repair round (ledger amendments explicitly permitted). A production RC artifact/configuration and an approved production soak target are not identified by the lane assignment. Local rejection/safety tests cannot substitute for an exact-RC sustained soak.

## Reproduced gate result

`uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` passed: 1322 reviewed identities / 1322 findings, zero unclassified or never-allowlist findings, base `ab8b3737fa64`. No ledger amendment or dead-code removal is supported by this scan; the conditional ledger edit is skipped.

The supplied historical check-3.log is a pytest failure, not a vulture failure: `test_ensure_schema_fences_ddl_behind_advisory_lock` expected 21 statements but observed 24. The current test will be rerun before deciding whether any repair is needed.

Profile review independently confirms that `run_soak.py` is explicitly a host-process preflight, not the production Compose RC; its profile documents missing user/Workspace population, successful model/tool work, fan-out and physical execution fencing. No prolonged preflight can satisfy exact-RC acceptance.

## Focused validation

All commands below were executed in the assigned worktree with a 1200-second timeout:

- Exact vulture command above: PASS, 1322/1322 identities.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`: PASS, 37 passed / 6 skipped. The historical failure no longer reproduces. The current independent expected-DDL list includes all three validation audit columns at lines 174–176; no weakened assertion or repair is needed. Skips are not PostgreSQL integration proof.
- `uv run pytest tests/test_soak_promotion_gates.py -x -q`: PASS, 72 passed. Includes real production middleware replica-selection counterevidence and production task-router cross-replica receipt 404 observations, alongside mocked HTTP failure cases and real process-group sampling. These are local regression probes, not a deployed soak.
- `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: PASS, 1 passed.
- `uv run python scripts/check-backlog-consistency.py`: PASS, 168 items.
- `git diff --check`: PASS.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3301 files already formatted.

## Architecture reconciliation

Read repository `AGENTS.md`, `docs/README.md`, the load profile, and ADR-081, ADR-081626-f383 and ADR-082426-82c7. ADR-081 is **Proposed**, not accepted promotion authority. Accepted occurrence claims establish canonical admission identity, not physical-work uniqueness; accepted execution fencing explicitly does not itself define lease-expiry takeover. No second scheduler, execution authority, authorization path, or store was introduced. Unproven reclaim semantics cannot be silently manufactured to satisfy the issue.

## Acceptance disposition (all ten criteria)

| Criterion | Independently checked evidence / residual gap |
| --- | --- |
| 1. Representative profile | UNVERIFIED: `docs/testing/soak/m3a-load-profile.md` defines a preflight mix but explicitly excludes/misses concurrent users/Workspaces, fan-out, successful tool/model work and Design/Canvas coverage. |
| 2. Production replicas | UNVERIFIED: no exact-RC production multi-replica run executed this round. ASGI instances are not deployed replicas. |
| 3. Sustained load | UNVERIFIED: local tests do not observe sustained saturation, reclaim, backoff or leaks. No four-hour RC run supplied/executed. |
| 4. Physical-work uniqueness | UNVERIFIED: `scripts/soak/run_soak.py:1067` cancels the admission probe Run without physical execution. Occurrence deduplication is not physical Attempt/reconciliation proof. |
| 5. Replica-independent enforcement | UNVERIFIED with counterevidence: executed `tests/test_soak_promotion_gates.py:439` observes independent `[200, 200, 429]` allowances for the same identity on both production middleware instances. `packages/maistro-server/src/maistro_server/api/rate_limit.py:94` constructs process-local limiter state. |
| 6. Production telemetry | UNVERIFIED: the executed process sampler test proves child RSS/FD accounting, not production pool/query/lock/application-loop/worker metrics with complete thresholds. |
| 7. Active-work restart recovery | UNVERIFIED: boot cleanup tests are not a killed active physical Attempt recovery/drain/fencing experiment. |
| 8. Exact-RC long soak | UNVERIFIED: `scripts/soak/run_soak.py:744` always rejects host preflight artifact equivalence; all three four-hour preflight CLI rejection cases passed. No identified RC image/configuration was exercised. |
| 9. Findings disposition | UNVERIFIED: this local report records blockers but does not prove complete milestone filing/reclassification. No GitHub mutations permitted/performed. |
| 10. Hash-bound published evidence | UNVERIFIED: this report identifies the tested source HEAD but is not a machine/human production soak evidence pack tied to exact RC image/package/configuration hashes. |

## Handoff

Only this report changed; no source, tests, inventory counts, or ledgers changed. Existing meaningful regression tests were executed rather than duplicating coverage solely to create a test delta; no inventory note is required for a documentation-only checkpoint.

Verdict: **BLOCKED** for issue acceptance, despite passing focused CI validation. The requested vulture failure and historical pytest failure do not reproduce and must not trigger guessed ledger or cosmetic source repairs.

Next required input/work is an identified immutable RC artifact/configuration and a representative production-topology execution plan covering the gaps above, followed by a fresh sustained run and findings disposition. Replica-independent enforcement also needs an explicit production contract resolution; the current local limiter cannot prove the stronger #860 claim. Repeating preflight or this same CI repair does not resolve these blockers.

Snapshot accounting: checked 1 assigned issue; done 0 acceptance-complete issues; skipped 0 issues (conditional ledger edit unnecessary); command errors 0. Validation complete; local documentation commit is the handoff, not integration approval.
