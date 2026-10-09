# Issue #860 — c6b011fe CI repair

## Frozen scope

- Assigned issue: #860; branch `auto-860` in `/home/dev/Git/wt/auto-860`.
- Starting HEAD: `18dab15c0a42013c646e5e2b55be166c56b68e73` (verified); supplied base: `cd5618223cbdd9ac55d40695987e09fd8b4ef184`.
- Worktree initially clean; no incoming changes to salvage.
- Process only the assigned vulture exact-debt-ledger repair, adjacent soak tests, and #860 acceptance evidence. No GitHub mutations or new runtime authority.
- Candidate edits: this report and `quality/vulture-baseline.json`; production removals only if the prescribed scan proves genuinely dead identities. Any added tests require an inventory note.
- Job directory initially contains no `check-*.log` files. Run validation locally rather than relying on previous claims.
- Ambiguity: the assignment includes the full soak issue plus an explicit CI repair. Proceed with the concrete CI repair; do not claim issue completion without exact-RC sustained evidence.

## Progress

The prescribed vulture command passed on the starting HEAD: 1,338 findings,
1,338 reviewed identities, zero unclassified and zero never-allowlist findings.
Log: job directory `check-vulture-before.log`. No unbanked identity exists to
repair; changing the ledger would be unsupported. The gate selected merge-base
`94781cf6b708`, recorded rather than confused with the dispatch base.

The supplied previous result exists and reports BLOCKED. Current profile review
independently confirms the runner is a host-process preflight, not the promoted
Compose artifact, and explicitly leaves representative workloads and physical
Attempt fencing unverified.

Focused validation passed: `uv run ruff check .`; `uv run ruff format --check .`;
`git diff --check cd5618223cbdd9ac55d40695987e09fd8b4ef184...HEAD`; and
`uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`
(61 passed). The historical whitespace finding does not reproduce against the
assigned base. Logs are in the job directory.

Architecture reconciliation: ADR-081 is Proposed, not an accepted topology
waiver. Accepted ADR-081426-1f7c identifies physical execution with Attempt IDs;
unique Run admission is not physical-work fencing evidence. Accepted ADR-085
requires principal-keyed rate limits. Current middleware explicitly documents
process-local budgets; this does not establish #860's replica-selection
non-bypass criterion. No competing execution, authorization, or event authority
was introduced.

Additional executed checks (all exit 0):

- `uv run python scripts/check-ratchet-provenance.py`
- `uv run python scripts/check-shipped-surface-truth.py`
- `uv run python scripts/check-suite-inventory.py`
- `uv run python scripts/check-backlog-consistency.py`
- Inline `uv run python` importing the current soak evaluator and evaluating
  `evidence/m3a-round6-shakedown.json`: asserted rejection for both
  `sustain_duration` and `exact_rc_artifact`. Output saved as
  `check-historical-evidence.log`; this is a rejection check, not a new soak.

## Acceptance assessment

| #860 criterion | Current executed evidence / limitation |
| --- | --- |
| Representative RC profile | UNVERIFIED. `m3a-load-profile.md:152-165` records missing multi-user/Workspace, Graph/tool/model/Canvas, Goal and worker workloads. |
| At least two application replicas | UNVERIFIED for the exact production RC. Focused tests exercise two middleware instances, not deployed replicas. |
| Sustained saturation, growth, reclaim, retries and leaks | UNVERIFIED. Historical evidence records 90.43 seconds against 14,400 required (`evidence/m3a-round6-shakedown.json:221-224`); current evaluator rejects it. |
| Exactly-once/fenced physical work and Goal reconciliation | UNVERIFIED. Admission probe edge cases pass, but Run identity deduplication does not prove physical Attempt fencing or sustained Goal reconciliation. |
| Security/rate/degraded behavior, no replica-selection bypass | NOT MET for a shared allowance: executed `test_replica_selection_has_an_independent_production_allowance` proves both instances return 200,200,429 for the same identity. Middleware is intentionally process-local (`packages/maistro-server/src/maistro_server/api/rate_limit.py:25-30,72-76`). Backpressure route test passes; this is not a deployed security soak. |
| Complete thresholded telemetry | UNVERIFIED in production. Process-group sampler regressions pass; application event-loop latency and detached workers remain uncovered. |
| Kill/restart during active physical work without loss/duplication | UNVERIFIED. No current production kill/restart executed. Historical rejoin/terminal Run counts do not prove physical-work recovery. |
| Long exact-RC soak | NOT MET by available evidence. `scripts/soak/run_soak.py:635-647` truthfully rejects the host-process artifact; CLI fail-closed regressions pass. No supplied immutable production RC/config identity was exercised. |
| Findings classified to earliest broken invariant | Backlog consistency gate passes; completeness of load-finding classification remains UNVERIFIED. No GitHub mutations performed. |
| Human/machine evidence tied to current artifact/config hashes | UNVERIFIED for promotion. This report and job logs bind validation to the starting HEAD, but do not provide current production image/config soak evidence. |

## Handoff

Verdict: **BLOCKED** for issue #860, not a failing vulture gate. The prescribed
CI repair has no reproducible violation. Do not manufacture a baseline amendment,
weaken the artifact/duration gates, or rerun this same no-op repair expecting a
production result. Next work requires selecting the immutable production RC and
configuration, implementing representative production-path workloads/telemetry,
resolving the replica-budget acceptance conflict, and executing the required
sustained recovery soak. The current preflight cannot certify that result.

Changed file: this report only. No production code, quality ledgers, tests, or
suite counts changed; no inventory delta is required. Prior work is preserved.
Progress: checked 1 assigned item, done 0 issue acceptances, skipped 0 items,
errors 0 validation commands; next: production-soak prerequisites above.
