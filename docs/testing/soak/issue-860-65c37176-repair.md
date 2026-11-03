# Issue #860 — repair checkpoint (65c37176)

## Frozen scope

- Only issue #860, branch `auto-860`, starting HEAD
  `47050444e6b65f067405b67bbe8bb2d61e7be99c`, supplied base
  `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Inspect the supplied dispatch snapshot and prior failure log; no GitHub mutations
  or refreshed issue/PR enumeration.
- Review `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`,
  `docs/testing/soak/m3a-load-profile.md`, relevant ADRs and CI gate configuration.
- Run the exact assigned vulture gate; amend `quality/vulture-baseline.json`
  only if actual findings require reviewed retained identities.
- This report is the planned checkpoint file. Additional production/test edits
  require concrete evidence within this issue's scope.

## Initial observations

- Worktree clean; HEAD matches assignment. No incoming diff to salvage.
- Current job directory contains no `check-*.log` files.
- Prior result reports BLOCKED, not a verified release-candidate soak.
- Ambiguity: assignment calls for CI repair while the prior result identifies
  missing exact-RC deployment evidence. Treat these separately; a clean gate
  cannot establish the issue's operational acceptance criteria.

## First executed results

- Exact assigned vulture command passed (exit 0): 1,323 findings, 1,323
  reviewed identities, zero unclassified/never-allowlist findings. No ledger
  amendment is justified by this scan.
- Supplied historical `98a113.../check-3.log` is a pytest failure, not a
  vulture failure: schema fence test expected 21 DDL statements but observed 24.
  Current schema and test will be checked directly before calling it repaired.
- The frozen issue body has ten operational acceptance criteria. The profile
  explicitly identifies its host-process harness as preflight-only and says it
  cannot sign an exact production Compose soak.

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed, 3,270 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  **103 passed, 6 skipped**. This includes the historical schema-fence regression
  and both authenticated/unauthenticated independent-replica allowance tests.
  Current test explicitly expects the three Gauntlet audit columns absent from
  the historical failing expectation; no further repair to that test is needed.

## ADR reconciliation

Read ADR-081 (Proposed deployment topology), accepted ADR-081626-f383
(Attempt lease/fencing), ADR-082126-f69c (recurrence produces canonical Runs,
not a second execution runtime), and ADR-085 (per-principal rate limiting).
The issue must be satisfied through the canonical execution/authorization
paths. Neither one schedule admission nor independent per-process 429s proves
physical-work fencing or selection-proof principal enforcement. No competing
runtime/store or new authorization path is introduced by this round.

## Remaining executed checks

- Verified the vulture invocation matches `.github/workflows/quality.yml:1076`
  and `.github/workflows/vulture-ratchet.yml:80`.
- `uv run python scripts/check-ratchet-provenance.py`: exit 0; 53 quality JSON
  consumers have explicit provenance. Two non-fatal invalid-escape warnings
  were emitted by AST parsing; no gate violation.
- `uv run python scripts/check-shipped-surface-truth.py`: exit 0, complete matrix.
- `git diff --check`: exit 0.
- No tests added/modified, so no inventory delta. No code or ledger change:
  neither the historical failure nor the assigned vulture hypothesis reproduces.

## Acceptance assessment (frozen issue's ten criteria)

| Criterion | Executed evidence and disposition |
| --- | --- |
| Representative RC load profile | UNVERIFIED. Reviewed `m3a-load-profile.md`; one-key preflight omits concurrent Workspaces, successful model/tool work, Graph fan-out and other applicability decisions. No designated RC configuration supplied. |
| At least two production application replicas | UNVERIFIED. The passing tests exercise two ASGI middleware instances, not deployed RC images. No deployment soak executed this round. |
| Sustained saturation, queue growth, reclaim, retries and leaks | UNVERIFIED. Process sampler/accounting regressions pass, but are not a sustained production workload or lease-reclaim observation. |
| No duplicate physical work, including schedules and reconciliation | UNVERIFIED. `scripts/soak/run_soak.py:1044` cancels the queued schedule probe Run via the canonical store without executing it. Admission identity tests cannot establish physical Attempt uniqueness or Goal reconciliation. |
| Rate/security/degraded non-bypass across replica selection | UNVERIFIED overall; counterexample reproduced by both cases of `tests/test_soak_promotion_gates.py:439`: the same identity gets 200, 200, 429 independently on each replica. Production `rate_limit.py:93` constructs an `InMemoryRateLimiter` per middleware instance. Local enforcement is not a cluster-wide principal budget. |
| Complete telemetry and explicit thresholds | UNVERIFIED. Existing profile distinguishes driver event-loop lag from application lag and process-group measurements from container/worker coverage; no complete RC time series executed. |
| Active-work kill/restart, drain, fencing and recovery | UNVERIFIED. Boot-cleanup tests pass, but do not demonstrate recovery of active physical work. |
| Long unchanged exact-RC soak | UNVERIFIED / BLOCKED. `scripts/soak/run_soak.py:730` explicitly returns `ok: false` for host preflight. All three four-hour missing/null/preflight artifact CLI regressions pass (expected exit 1). No immutable RC/configuration designated; no four-hour deployment run performed. |
| Findings filed/reclassified before promotion | Local findings recorded here; external disposition UNVERIFIED. No GitHub mutation permitted or performed. |
| Machine/human evidence bound to image/package/commit/config hashes | UNVERIFIED for promotion. This report binds local checks to the starting source head, not to an executed deployment/configuration-bound soak. |

## Handoff

**BLOCKED.** Only this checkpoint report changes. The supplied historical CI
failure is already repaired at the assigned starting head; the exact vulture
scan has no unbanked identities. Amending a clean ledger or making unrelated
code edits would not address actual evidence.

Required next inputs/work: designate an immutable RC and supported runtime
configuration; resolve selection-proof rate semantics; complete representative
canonical physical-work workloads and telemetry; then run the unchanged
>=4-hour RC soak, with active-work interruption/recovery and hash-bound evidence.
Do not relaunch this scanner-repair round without new scanner findings or those
missing operational inputs. A longer host-process preflight cannot substitute.

Progress: checked 1 issue; acceptance-complete 0; skipped 0; validation errors 0;
blocked 1. All ten operational criteria remain unverified at promotion grade.

