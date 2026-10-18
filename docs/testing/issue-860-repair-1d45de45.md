# Issue #860 — repair checkpoint (job 1d45de45)

## Frozen scope

- Only issue #860, branch `auto-860`, starting HEAD
  `2f4dadd04d504d81228a5b663fdb0123d539c99b`, base
  `ab8b3737fa64f8d840f421ef87ca506c509444ff`.
- Worktree initially clean; no incoming edits to salvage.
- Inspect supplied dispatch, prior result and failed check, repository guidance,
  relevant execution ADRs, soak runner/tests and production limiter behavior.
- Run exact requested vulture gate; change its ledger only for actual reviewed
  findings. Validate focused soak/server tests and lint/format.
- Only planned output is this checkpoint unless validation identifies a focused
  repair in the inspected runner/tests/production files or vulture ledger.
- No GitHub mutations, ref changes, alternate execution authorities or promotion
  claims. Existing historical artifacts are preserved.

## Initial observations

The supplied prior result reports BLOCKED; its assertions will be checked rather
than accepted. The current job directory contains no `check-*.log` files at the
initial snapshot. The explicitly referenced previous job log will be inspected.

Assumption: this is a writer repair round, not the read-only verifier role.
Production soak acceptance is distinct from deterministic gate health.

## Results

The exact requested vulture scan passed: 1322 reviewed identities and 1322
findings, zero unclassified and never-allowlist entries. No ledger change is
justified. The referenced historical check-3.log is instead a pytest failure:
`test_ensure_schema_fences_ddl_behind_advisory_lock` expected 21 DDL statements
but observed 24. Current reproduction PASSED:
`uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
returned 37 passed / 6 skipped. No assertion weakening is needed; skipped
PostgreSQL cases are not integration evidence.

`uv run pytest tests/test_soak_promotion_gates.py -x -q`: 72 passed.
`uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
1 passed. All three commands used a 1200-second timeout.

The executed soak tests include production middleware instances observing
independent `[200, 200, 429]` allowances for the same identity on each replica,
and the production task router returning a peer-receipt 404. These are local
ASGI counterexamples, not a deployed soak. Synthetic evidence evaluator tests
also confirm host preflight cannot pass exact-RC promotion.

Read ADR-081 (Proposed), ADR-081626-f383 and ADR-082426-82c7 (Accepted).
Reconciliation: admission occurrence uniqueness is not physical-work uniqueness;
lease fencing does not by itself establish expiry/reclaim semantics. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt` and existing execution/store
ownership. Do not manufacture a new recovery authority to make the soak pass.

Final deterministic checks (1200-second timeout):

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3301 files already formatted.
- `uv run python scripts/check-backlog-consistency.py`: PASS, 168 items.
- `git diff --check`: PASS.

## Acceptance audit

The ten criteria below are from the supplied dispatch's issue body, not inferred
from prior reports. No production load run was executed this round.

| Criterion | Executed evidence and disposition |
| --- | --- |
| 1. Representative RC profile | UNVERIFIED. Reviewed `docs/testing/soak/m3a-load-profile.md:170`: one key, missing user/Workspace population, fan-out, successful tool/model work, Design/Canvas and background reconciliation. These exclusions still require a selected RC justification. |
| 2. Two supported production replicas | UNVERIFIED. Local ASGI tests exercise two production middleware/router instances, not two deployed RC application replicas. Profile explicitly describes host-process preflight. |
| 3. Sustained saturation/reclaim/backoff/leaks | UNVERIFIED. Focused tests are short regressions, not sustained load or lease-reclaim evidence. |
| 4. No duplicate physical work | UNVERIFIED. `scripts/soak/run_soak.py:1067` cancels the admission probe Run without executing it. Admission deduplication does not prove physical Attempt or Goal-reconciliation uniqueness. |
| 5. Replica-independent enforcement | UNVERIFIED with counterevidence. Executed `tests/test_soak_promotion_gates.py:439` observes fresh allowance on the second replica for both identity classes. `packages/maistro-server/src/maistro_server/api/rate_limit.py:94` constructs an in-memory limiter per instance; lines 32–37 document N-times aggregate scope. Stronger #860 semantics need contract resolution, not a claim that H3 proves a shared budget. |
| 6. Production telemetry with thresholds | UNVERIFIED. Executed sampler regression observes real child RSS/FD growth, but not production application loop lag, pool saturation, worker telemetry or full thresholded series. |
| 7. Kill/restart during active work | UNVERIFIED. Boot cleanup tests do not execute an active Attempt drain/recovery/fencing experiment. |
| 8. Exact-RC long soak | UNVERIFIED. `scripts/soak/run_soak.py:744` unconditionally rejects host preflight equivalence; three four-hour CLI rejection cases passed. Assignment identifies source refs but no immutable promotion image/configuration to exercise. |
| 9. Findings filed/reclassified | UNVERIFIED. This report records known blockers; it does not establish complete milestone disposition. No GitHub mutations performed. |
| 10. Hash-bound machine/human evidence | UNVERIFIED. This checkpoint binds deterministic validation to the starting source HEAD; it is not a production soak evidence pack with image/package/configuration hashes. |

## Handoff and next action

Verdict: **BLOCKED**. The specifically requested vulture repair has no reproduced
finding, and the referenced historical pytest failure is already corrected in the
starting tree (the expected DDL includes the three validation audit columns).
No source or ledger edits are warranted by those checks. Passing them cannot
resolve the production acceptance gaps.

Only `docs/testing/issue-860-repair-1d45de45.md` changed. No tests were added or
modified, so no suite inventory delta note is required. Existing source, tests,
ledgers and historical evidence were preserved.

Required next work: select the immutable promotion RC image/configuration and
supported topology, resolve the replica-budget contract, complete representative
physical-work/recovery workloads and telemetry, then execute the long-running
RC soak and disposition its findings. Do not redispatch the same passing vulture
scan as if it can supply missing production evidence.

Snapshot accounting: checked 1; done 0 acceptance-complete; skipped 0 issues;
errors 0 current validation commands. Conditional ledger edit skipped because
there are no unbanked identities. Local documentation commit is a blocked
handoff, not integration approval.
