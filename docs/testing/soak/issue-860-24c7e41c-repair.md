# Issue #860 — repair checkpoint (24c7e41c)

## Frozen scope

- Assigned worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD `891da02b1c6443bbf9921319d5d560afd29efa23`; base `ac7370141e8e61bd6f352bca35ed0b505104aadb`; both supplied, HEAD verified. Initial worktree clean.
- Process only issue #860 and the supplied dispatch snapshot; no GitHub mutations or re-fetching.
- Read scope: dispatch issue and supplied prior failure/result, repository instructions, relevant execution/soak ADRs, `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`, adjacent production rate/admission/receipt code, vulture gate and CI configuration.
- Write scope: this handoff; `quality/vulture-baseline.json` only if the explicitly requested scan demonstrates retained unbanked identities; production/test edits only for demonstrated issue-860 defects, with inventory notes if tests change.
- Current job directory contains no `check-*.log` files. Supplied prior result reports BLOCKED, not acceptance; independently validate it.
- Ambiguity: dispatch includes both verifier and writer directions. Assigned repair and mandatory local commit identify this as the writer lane.

## Progress

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` (matches `.github/workflows/vulture-ratchet.yml:82–85`): exit 0, 1322 findings / 1322 reviewed identities, zero unclassified and never-allowlist identities. No ledger edit is justified by this evidence.
- Historical `98a11313/check-3.log` is a schema test failure (24 DDL statements vs 21 expected), not a vulture failure.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`: **37 passed, 6 skipped**. Historical failure does not reproduce; skipped PostgreSQL integration tests are not live DB evidence.
- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3301 files already formatted.
- Read all ten acceptance criteria from the frozen issue body and the complete load profile. The profile explicitly identifies the current harness as a preflight emulator, not the exact RC topology. Promotion acceptance remains pending independent code/test inspection.
- `uv run pytest tests/test_soak_promotion_gates.py -x -q`: **72 passed**. These include real production middleware/route probes, but most harness responses are simulated and none constitutes a deployed production soak.
- Read accepted ADR-081226-69ee, ADR-081626-f383 and ADR-082526-b36a completely. Preserve Goal -> Graph -> Run -> NodeRun -> Attempt. The later renewal/reclaim ADR extends the original fencing boundary; do not confuse missing load evidence with an absent reclaim implementation.
- Inspected `pg_learnings.py:215–222` and its schema test: upgrades execute inside the transaction/advisory lock, and test lines 173–175 already include the three columns missing in the historical failed log.
- `run_soak.py:744–755` explicitly returns `exact_rc_artifact.ok=false`. The executed four-hour CLI rejection tests confirm that duration cannot establish artifact equivalence.
- Production middleware creates its own `InMemoryRateLimiter` (`rate_limit.py:93`). Executed test `test_replica_selection_has_an_independent_production_allowance` observes `[200, 200, 429]` on each of two instances for the same identity. Production receipt route (`tasks.py:144`) reads the injected queue; executed router probe observes owner 200 and peer 404. Neither probe establishes deployed ingress behavior.
- `uv run python scripts/check-ratchet-provenance.py`: passed, 53 consumers with explicit provenance. The gate selected trusted base `321cbdb8fe9b`; no baseline changes made. Non-fatal invalid-escape SyntaxWarnings emitted.
- `git diff --check`: passed. Supplied develop base resolves locally; no sync conflict exists.

## Acceptance disposition

| Issue criterion | Evidence / limitation |
|---|---|
| Representative workload | **UNVERIFIED**. Inspected complete profile: one API key, degraded model path; concurrent Workspaces, Graph fan-out and successful tool/model/Design/Canvas traffic remain gaps. |
| At least two deployed replicas | **UNVERIFIED**. Executed ASGI two-instance probes, not the supported production deployment. |
| Sustained saturation, reclaim, retry and leak observations | **UNVERIFIED**. No sustained production load executed in this repair. Deterministic suites cannot prove long-window resource behavior. |
| No duplicate physical work | **UNVERIFIED**. Schedule occurrence probe described in the profile cancels its queued Run without physical execution; admission identity alone cannot discharge this criterion. |
| Replica-resistant rate/security/degraded enforcement | **UNVERIFIED** for deployed topology. Independent production middleware allowances reproduced for authenticated and unauthenticated identities; per-instance enforcement is not a cluster-wide principal budget. |
| Complete telemetry with thresholds | **UNVERIFIED**. Profile contains thresholds; driver-side query/loop probes are not application query/loop telemetry, and process-group sampling does not include detached workers. |
| Active-work kill/restart/drain/fencing/recovery | **UNVERIFIED**. Process health/rejoin and terminal Run counts do not establish physical Attempt recovery. |
| Long soak of exact RC artifact/configuration | **UNVERIFIED / BLOCKED**. Current driver intentionally fails exact-artifact equivalence; CLI rejection executed even for synthetic four-hour evidence. No immutable RC deployment/configuration was supplied or exercised this round. |
| Findings filed/reclassified before promotion | **UNVERIFIED** for completeness. Existing local findings preserved; no GitHub mutations permitted or performed. |
| Machine/human evidence tied to exact hashes | **UNVERIFIED** for promotion. This source-bound validation report is not a deployed image/package/configuration-bound soak pack. |

## Handoff

**BLOCKED**, not merge-ready. The supplied CI failure is stale at the assigned
HEAD, and the required vulture scan is clean. Do not manufacture a repair by
weakening tests, amending an already exact ledger, or bypassing the exact-RC
guard. No production/test/ledger changes were warranted by the executed checks;
only this report changed. No new tests, so no inventory delta is required.

Next requires a release-owner-selected immutable RC image and configuration,
representative workload and application telemetry, followed by a fresh >=4-hour
production soak with observed active physical-Attempt failure/recovery. Resolve
replica enforcement and receipt visibility through existing canonical owners,
not a parallel scheduler/store/authentication mechanism. Repeating the same
successful deterministic checks is not progress toward those missing criteria.

Progress: {checked: 1, done: 0, skipped: 0, errors: 0, next: exact-RC production acceptance evidence}.
This checkpoint is committed locally; no push, PR, issue closure or integration approval.
