# Issue #860 — bounded CI repair, job 20a7fa3f

## Frozen scope

- Only issue #860; assigned worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD `6c9ee497c2032f74bfda35cc5a27db41251d4a75`; base `af799688335f9a7dba7999a05e0e13f102c6c5ae`.
- Initial tree clean. No salvage necessary. No GitHub changes or ref updates.
- Inputs: supplied dispatch-context.json, prior result 48e72b66, prior check-3.log from 98a11313, repository instructions/ADRs, existing soak runner/profile/tests, vulture gate and ledger. Edit scope: this report and only reproduced issue-related vulture defects/retained identities (plus regression test/inventory note if needed).
- Current job directory has no check-*.log files; run checks locally rather than infer success.
- Assumption: this is the explicitly authorized vulture CI-repair round, not authorization to change production concurrency/security architecture or accept old soak evidence.

## Progress

- Exact requested vulture command passed: 1,328 findings, 1,328 reviewed identities, zero unclassified/never-allowlist. No unbanked identities to repair; no ledger amendment justified. The gate selected base `72f5dedd3db3` automatically, so this is not yet an explicit dispatch-base comparison.
- Historical check-3.log failed the learnings schema-fence test (24 SQL statements versus 21 expected). Current test independently lists the three Gauntlet columns and passes: `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` → 37 passed, 6 skipped. No test weakening or further repair needed. Skips are database-dependent; this run does not prove live concurrent DDL.
- `uv run ruff check .` passed; `uv run ruff format --check .` passed (3,159 files).
- Read the load profile and production schema implementation. The profile explicitly excludes promotion equivalence for the host emulator and documents missing representative workloads. Acceptance review continues; no promotion claim.
- `uv run pytest tests/test_soak_promotion_gates.py -x -q` → 65 passed. This includes real production middleware instances demonstrating independent authenticated/anonymous replica allowances, not cluster-wide non-bypass. Production wiring is `maistro_server/main.py:648`.
- `uv run python scripts/check-backlog-consistency.py` passed (168 items).

## Architecture reconciliation

Read ADR-081 (Proposed, not accepted authority), accepted ADR-081226-a66b and ADR-081626-f383. Canonical Run/NodeRun/Attempt lifecycle and durable lease fencing remain authoritative. ADR-081626-f383 explicitly leaves lease-expiry takeover/recovery supersession outside its current contract: #860 cannot silently implement a second recovery authority to manufacture acceptance. Similarly process-local rate enforcement is not cluster-wide non-bypass. No runtime, scheduler, authorization or gate changes are warranted by the reproduced CI results.

## Final validation

- Verified the dispatch base resolves, then ran `RATCHET_BASE_REV=af799688335f9a7dba7999a05e0e13f102c6c5ae uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: passed, 1,328 reviewed identities and findings. The gate still reports trusted baseline `72f5dedd3db3`; no provenance logic changed.
- `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: 1 passed.
- Executed the current runner's `failed_promotion_checks` against `docs/testing/soak/evidence/m3a-round30-shakedown.json`: exactly `sustain_duration` and `exact_rc_artifact` failed. Asserted both failures and asserted `preflight_artifact_check()['ok'] is False`. The JSON records 420.08 seconds, below 14,400 seconds. This is rejection of historical evidence, not a newly executed soak.
- No new tests or changed test counts; inventory note not needed. No production code, ledger, grants, gates, historical evidence or deployment files changed.

## Acceptance matrix (issue body, all ten criteria)

| Criterion | Executed evidence / remaining gap |
|---|---|
| Representative RC profile | **UNVERIFIED** completeness. Read `m3a-load-profile.md`; it explicitly lacks concurrent user/Workspace population, fan-out, successful tool/model calls and Design/Canvas workloads. |
| Two production application replicas | **UNVERIFIED** on this candidate. ASGI middleware instances are not production replicas; runner artifact check explicitly identifies host preflight. |
| Sustained saturation/reclaim/retry/leak observations | **UNVERIFIED**. Historical 420.08-second evidence is rejected by the duration gate; no new sustained run performed. |
| No duplicate physical work, including Goal reconciliation | **UNVERIFIED**. Admission/probe tests cannot establish physical Attempt side effects; canonical fencing must remain authoritative. |
| Concurrent rate/security/degraded behavior cannot be bypassed by replica selection | **Not proven**. Passing tests at `tests/test_soak_promotion_gates.py:439` execute real middleware and show the same principal gets independent `[200, 200, 429]` allowances on each instance. `maistro_server/main.py:648` wires this middleware in production. Backpressure test passes, but does not prove the full criterion. |
| Complete telemetry with thresholds | **UNVERIFIED** for production: profile's driver-loop lag is not application event-loop lag; long-window worker/pool/lease observations remain absent. |
| Kill/restart during active work with drain/fencing/recovery | **UNVERIFIED**. Historical drain/terminal-count observations do not prove active physical work was neither lost nor duplicated. |
| Long exact-RC soak; rerun after runtime/config changes | **UNVERIFIED**, historical candidate explicitly fails both promotion gates when evaluated now. Current host runner cannot sign an exact-RC soak (`run_soak.py:730`). |
| Findings filed/reclassified to earliest invariant | **UNVERIFIED** completeness. Local gaps recorded here; no GitHub mutation permitted or performed. |
| Human/machine evidence bound to exact promoted hashes | **UNVERIFIED** for current candidate. Existing files are historical evidence, not an exact-candidate promotion proof. |

## Disposition / next owner

**BLOCKED for issue acceptance**, not a reproduced vulture CI failure. The prior schema-fence failure is already fixed at the assigned starting HEAD. Do not manufacture ledger edits or rerun the host emulator for four hours as a substitute for the exact RC topology. Next work requires an identified immutable RC/config, a representative production-path workload with physical-work observations, and explicit resolution of the non-bypass/reclaim contract gaps. This round makes no integration or closure recommendation.

Changed file: this report only. Local commit required before handoff. Progress: checked 1 issue; done 0; skipped 0; validation-command errors 0; blocked 1. No additional issues/PRs processed.
