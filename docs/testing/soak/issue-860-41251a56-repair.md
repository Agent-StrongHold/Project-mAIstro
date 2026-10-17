# Issue #860 — bounded repair 41251a56

## Frozen scope

- Assigned issue: #860 only; branch `auto-860` in `/home/dev/Git/wt/auto-860`.
- Starting HEAD: `47231249096d3a25071371767780fc7a1d3372df` (resolved; clean).
- Assigned base: `435dc1937e0407ab4de198ffcced49860bb14ad2` (resolved).
- Evidence snapshot: supplied `dispatch-context.json`, prior result `ccb08ed4462642a59f90dbd09ea571c6/result.json`, and `98a11313167b41a98a420abfda80c292/check-3.log`. No check logs were present in this job directory at start.
- Process only the reported schema-fence failure, exact vulture CI gate, and #860 acceptance validation. Candidate repair files: `packages/maistro-core/tests/persistence/test_pg_learnings.py`, `packages/maistro-core/src/maistro/persistence/pg_learnings.py`, `quality/vulture-baseline.json` (only if actual scanner evidence warrants), this report, and a corresponding inventory note if tests change. Soak runner/tests/profile and referenced ADRs are read/validation inputs, not expansion into other issues.
- No remote mutations, new scheduler/authority, or unrelated branch repairs.

## Initial evidence and assumptions

The prior log reports 24 DDL statements versus 21 expected in the schema fence test. This must be reproduced against this HEAD before changing it. The prior result reports absent designated RC/configuration and independent replica rate allowances; neither is accepted without fresh checks. A local checkout is not assumed to be the RC that #89 will promote. The large inherited diff against the assigned base is preserved, not rewritten.

## Fresh validation checkpoint

- Exact requested vulture scan PASS: 1323 findings / 1323 reviewed identities; zero unclassified and forbidden findings. Gate-selected trusted base `4aa68edc0b6b`. No ledger amendment warranted.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`: 37 passed, 6 skipped. Historical failure no longer reproduces: the expected DDL list already includes the three validation audit columns at lines 175–177. Do not remove those assertions or amend working code to satisfy a stale log.
- Logs stored in the supplied job directory as `worker-vulture.log` and `worker-schema.log`.
- Fresh inspection confirms `preflight_artifact_check()` hard-codes non-RC status; existing two-instance production middleware tests assert independent allowances. Executed these next, rather than claiming a new production soak from synthetic evidence.

## Focused validation completed

- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: **66 passed**, including real middleware-instance replica-selection probes, preflight CLI rejection, process-group sampler tests, and task backpressure behavior. Log: `worker-soak-tests.log` in the supplied job directory.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS (3270 files).
- `uv run python scripts/check-deployment-claims.py`: PASS.
- `uv run python scripts/check-execution-lifecycles.py`: PASS (19 classified/discovered lifecycles). CI command forms checked in `.github/workflows/ci.yml` and `quality.yml`. Logs: `worker-gates.log` in the supplied job directory.

These are fresh local checks, not acceptance of previous production-soak claims. The six PostgreSQL-dependent skips are not passes. No new tests or test changes; inventory delta is zero and no inventory note is needed.

## Architecture reconciliation

Read repository instructions, documentation authority map, ADR-081 (Proposed), ADR-085 (Accepted), ADR-081426-1f7c (Accepted), and ADR-082526-b36a (Accepted). Physical execution identity is Attempt, not an admission receipt; renewal/reclamation belongs to the canonical lifecycle. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`. No new execution, event, authorization or reconciliation authority is introduced. Per-principal keying in ADR-085 does not establish a shared cross-replica allowance; the local-limiter result is not an acceptance waiver.

## Acceptance assessment

| #860 criterion | Fresh executed evidence or explicit gap |
| --- | --- |
| Representative RC load profile | **UNVERIFIED**. `m3a-load-profile.md:152` explicitly records missing multi-user/Workspace, fan-out, successful tool/model, Design/Canvas and background reconciliation traffic. No designated RC applicability decision supplied. |
| At least two application replicas | **UNVERIFIED for deployed RC**. Executed tests exercise two real middleware instances, not promoted images/services. |
| Sustained saturation, growth, reclaim, retry/backoff, leak and shutdown observations | **UNVERIFIED**. No sustained production window executed this round; targeted test duration is not a soak. |
| No duplicate physical work across replicas | **UNVERIFIED**. Admission probe tests require observed Run identity, but neither admission receipts nor terminal counts prove physical Attempt effects. |
| Rate/security/degraded enforcement cannot be bypassed by replica selection | **Aggregate allowance claim falsified** by executed `tests/test_soak_promotion_gates.py:439`: both authenticated and unauthenticated same identities receive `[200, 200, 429]` independently on each production middleware instance. `packages/maistro-server/src/maistro_server/api/rate_limit.py:93` constructs a local limiter. Task retryable backpressure tests pass; other security/concurrency acceptance remains **UNVERIFIED**. |
| Complete metrics with explicit thresholds | **UNVERIFIED at RC grade**. Sampler tests pass, but driver-loop lag does not measure application-loop lag; required worker/pool/reclaim and long-window observations remain missing. |
| Active-work replica kill/restart with drain/fencing/recovery | **UNVERIFIED**. No production replica restarted in this round; process cleanup tests are not physical-work recovery proof. |
| Long-running exact RC artifact/configuration | **UNVERIFIED / BLOCKED**. No designated immutable RC/configuration supplied. `scripts/soak/run_soak.py:730` marks host preflight non-RC; executed CLI tests reject even four-hour synthetic evidence without an exact artifact. |
| Findings filed/reclassified before promotion | **UNVERIFIED externally**. Local blockers recorded here; no GitHub mutations permitted or performed. |
| Publish machine/human evidence tied to exact image/package/commit/config hashes | **UNVERIFIED for RC**. This report and job logs document validation only, not a new hash-tied RC soak. |

## Handoff

**BLOCKED**. Only this report changes; existing work is preserved. No source or ledger amendment is justified by the actual passing scan and non-reproducing historical failure. No guessed repair, test weakening, or speculative infrastructure launch.

Next: obtain the release owner's immutable RC/configuration and representative workload applicability decision; resolve the cross-replica rate-budget acceptance mismatch; then run a production-topology soak with physical Attempt-effect correlation and complete metrics for the required long window. Do not rerun this unchanged repair lane without new inputs or a new failing check.

Progress: checked 1 issue; done 0 acceptance-complete issues; skipped 0 issues; errors 0 validation commands. Local commit of this report is the repair checkpoint, not integration approval.
