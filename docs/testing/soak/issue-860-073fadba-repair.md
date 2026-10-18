# Issue #860 — repair checkpoint (073fadba)

## Frozen scope

Only issue #860, branch `auto-860`, starting head
`c5fb7b9fc0c4348a6cdd570ad042267a8f2a97f2`, supplied base
`2f56be40ad241262b0384ab0b97834ebd37fe4d7`.
Initial worktree clean. No salvage patch needed.
No driver `check-*.log` files in the supplied job-directory snapshot.

Files under review: repository instructions and relevant ADRs;
`scripts/check-vulture-baseline.py`, `quality/vulture-baseline.json`;
`scripts/check-suite-inventory.py`, relevant inventory notes;
`scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`;
`packages/maistro-server/src/maistro_server/api/rate_limit.py` and adjacent
server tests; `docs/testing/soak/m3a-load-profile.md`,
`docs/testing/soak/evidence/m3a-round43-shakedown.json`;
this checkpoint. No unrelated issues or PRs will be processed.

Assumption: explicit writer/CI-repair assignment applies, not the generic
verifier-only no-edit instruction. Ledger changes require actual scanner
findings; absent findings, leave the ledger unchanged. Missing representative
RC evidence cannot be repaired by weakening promotion checks.

## Progress

- Verified supplied starting head and clean worktree.
- Extracted all ten acceptance criteria and read supplied prior result.
- Executed exact vulture command: PASS, 1322 reviewed identities / 1322
  findings, no unclassified or forbidden entries. No ledger repair justified.
- Executed `uv run python scripts/check-suite-inventory.py --suite tests`:
  FAIL, expected 5353, collected 5354. Investigating the extra identity before
  recording any delta. Logs: `/tmp/860-073fadba-{vulture,inventory}.log`.
- Production limiter explicitly remains process-local; existing preflight profile
  explicitly excludes representative workload surfaces and exact RC topology.
  These are acceptance blockers, not reasons to change the canonical executor.
- Inventory isolation: only three root test files differ from supplied base;
  their focused collection returns 100 nodes. Branch inventory-note changes
  sum to +93. Existing +1/-1 wheel-verifier notes cancel correctly. No tests
  or collection policy have been changed in this round.
- Read accepted ADR-081226-a66b (Run/NodeRun/Attempt lifecycle),
  ADR-082426-82c7 (occurrence claim belongs to Run), ADR-085 (canonical
  per-principal limits), ADR-073126-c4e1 (immutable RC/promoted artifacts),
  ADR-082526-547c (per-change inventory deltas). ADR-081 is Proposed, not
  accepted authority. Initial guessed deployment ADR filename was not found;
  skipped and used the actual registered file. No execution or auth authority
  changes are warranted by this CI repair.
- `uv run ruff check .`: PASS. `uv run ruff format --check .`: PASS,
  3306 files.
- Focused pytest (soak gates, gitleaks contract, production boot contract,
  server rate limiting and task concurrency backpressure): **127 passed**.
  Log: `/tmp/860-073fadba-focused.log`.
- Inventory arithmetic: soak tests = 84, new gitleaks tests = 8, boot tests
  = 8 (7 at supplied base). Net changed-file addition = 93, matching the
  +93 note sum. Remaining root-suite +1 provenance is **UNRESOLVED** after
  two diagnostic passes; do not bank an unexplained count or change the
  collection policy. No inventory delta is claimed for this docs-only round.

## Completed validation

All commands ran in the assigned worktree with long timeouts, not against
another clone. No driver logs were supplied for this job; prior-job results
were treated as allegations and the relevant checks rerun.

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS, 1322 findings match 1322 identities; exact workflow arguments verified at `.github/workflows/quality.yml:1079` |
| `uv run python scripts/check-suite-inventory.py --suite tests` | FAIL, expected 5353, collected 5354; no collection errors or duplicated evidence |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_gitleaksignore_contract.py tests/test_prod_stack_boot_contract.py --collect-only -q` | PASS, 100 nodes (84 + 8 + 8) |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS, 3306 files |
| `uv run pytest tests/test_soak_promotion_gates.py tests/test_gitleaksignore_contract.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_rate_limit.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | PASS, 127 tests |
| `uv run pytest packages/maistro-server/tests -x -q` | PASS, 566 passed, 8 skipped, 23 deprecation warnings; `/tmp/860-073fadba-server.log` |
| `uv run python scripts/check-deployment-claims.py` | PASS; existence of named components/backends only, not a deployment or soak proof |
| `uv run python -` importing `scripts/soak/run_soak.py` and evaluating round43 JSON | PASS assertion: failures exactly `['sustain_duration', 'exact_rc_artifact']`; current runner still returns `ok: false`, topology `host-uvicorn-preflight` |

## Acceptance evidence and remaining blockers

| #860 criterion | Executed evidence / disposition |
| --- | --- |
| 1. Representative RC load profile | **UNVERIFIED**. `m3a-load-profile.md:168-183` explicitly omits concurrent user/Workspace population, fan-out, successful tool/model/Canvas and reconciliation workloads. Existing harness tests cannot fill those workload gaps. |
| 2. Two supported production replicas | **UNVERIFIED**. Two production middleware instances are exercised by passing ASGI regressions; these are not a deployment. Profile lines 16-24 and the live artifact evaluator classify the runner as host preflight. |
| 3. Sustained saturation/reclaim/leak observation | **UNVERIFIED**. Executed evaluator rejects 420.09 seconds against 14400; no new long-running RC load was run. |
| 4. No duplicate physical work / Goal reconciliation | **UNVERIFIED**. Profile lines 215-218 admits the occurrence probe cancels its Run without executing physical Attempts, and sustained mix has no schedule traffic. Canonical admission uniqueness does not prove physical fencing. |
| 5. Replica-independent rate/security/degraded behavior | **FAILED**. Executed `test_replica_selection_has_an_independent_production_allowance` for both identities: same principal/IP gets `[200, 200, 429]` independently on each replica. Production `rate_limit.py:32-36` explicitly implements N-times allowance. Other server rate/auth/backpressure tests pass, but do not cure this criterion. |
| 6. Required production telemetry and thresholds | **UNVERIFIED**. Process-group sampler tests pass; profile lines 179-183 admits driver-loop lag is not application-loop lag and production worker/pool/reclaim observations remain absent. No exact-RC telemetry captured this round. |
| 7. Kill/restart graceful fencing and recovery | **UNVERIFIED**. Round43 records preflight drain/rejoin, not a new production physical-work recovery experiment. |
| 8. Long exact-RC soak | **FAILED** for supplied evidence: live evaluator returns duration and artifact failures. No immutable RC image/configuration selected by the assignment. Running the existing harness longer cannot satisfy artifact identity. |
| 9. Findings filed/reclassified | **UNVERIFIED**. This local report records blockers; no GitHub mutation was performed, and historical filing claims were not promoted to verified acceptance. |
| 10. Machine/human evidence tied to promoted hashes | **UNVERIFIED** for the promoted artifact. Existing JSON/human profile is inspectable but explicitly non-RC; no new RC identity evidence was produced. |

## Handoff

Changed only this report. No runtime, tests, quality ledger, grants, inventory
baseline, or gates changed. In particular there are no unbanked vulture
identities to amend, so the CI-repair ledger exception does not justify churn.
The existing meaningful regressions were executed rather than duplicated.

This is a partial validation handoff, **NEEDS-REPAIR**, not an implementation
completion or integration approval. No short soak was rerun merely to generate
another non-promotable evidence pack. The assignment has no selected immutable
RC image/configuration and the existing runner cannot sign promotion at any
duration. A coordinated limiter repair and representative production-path RC
runner/workload are still needed; neither is safely replaced by a gate waiver
or a second scheduler/authentication authority.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 1, next: "resolve unexplained inventory +1; select immutable RC and implement/run representative production soak after replica-budget repair"}`.
The error is the reproducible inventory-gate failure, not a validation timeout.

