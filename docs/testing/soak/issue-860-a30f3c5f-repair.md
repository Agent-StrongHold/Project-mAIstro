# Issue #860 — a30f3c5f repair validation

## Frozen scope

- Assigned issue: #860 only; writer in `/home/dev/Git/wt/auto-860`.
- Starting head: `94332bb86980aea66359930f04c59c0b0d1fedf2`.
- Provided base: `a586560170a9ce4d72ee7d750100d0178c1f69d0`.
- Initial worktree clean; no incoming edits to salvage.
- Inspect existing soak profile/evidence, harness and promotion tests, adjacent
  task-backpressure/learnings/rate-limit code and tests, applicable ADRs, and
  exact CI gate configuration. Only planned output is this validation record;
  code or ledger changes require an observed defect within this scope.
- Job directory snapshot contains no `check-*.log` files. Driver-check claims
  cannot be inspected; local validation is required.
- Prior result `af93736fc42a43c7ba83291e41b82ebd/result.json` says BLOCKED;
  that verdict is not treated as fresh execution evidence.

## Recorded results

- Exact requested vulture command executed successfully:
  `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`.
  1,342 findings match 1,342 reviewed identities; zero unclassified or
  never-allowlist findings. No speculative ledger amendment is justified.

## Assumption and remaining validation

This is the writer/CI-repair assignment, not the read-only verifier role.
A passing static gate does not establish load acceptance. No RC image digest or
promotion configuration is identified in the assignment; do not invent one or
substitute host uvicorn evidence. Further validation and final disposition below.

## Fresh validation checkpoint

- Ruff lint passed; format check passed (2,883 files).
- Focused pytest stopped at an actual failure:
  `test_pg_learnings.py:158` assumes exactly three schema statements, but
  current production `ensure_schema()` emits eight inside the fence.
  Inspect that schema upgrade before repairing the assertion; do not remove
  production DDL to make the historical test pass.
- CI-adjacent `check-ratchet-provenance.py` and
  `check-shipped-surface-truth.py` passed.
- Accepted ADR-081626-f383 owns fencing in canonical Attempt persistence;
  ADR-082126-f69c makes recurrence produce canonical Runs;
  ADR-082826-d9f5 keeps RunStore the sole execution authority. ADR-085's
  per-principal policy is not a waiver of replica-selection acceptance.
  ADR-081 remains Proposed. No competing runtime or authority is needed.
- The old H3 shared-store prose is already corrected in the starting tree.
  Production middleware explicitly instantiates a process-local limiter.

## Evidenced repair and validation

The develop merge brought five learning-stage upgrade statements into the
already-fenced production method. Updated the existing #860 test to check the
complete eight-statement ordered DDL body; retained BEGIN/lock-first/COMMIT-last
assertions. Production behavior is unchanged. Added zero-delta inventory note
`m3a-860-merged-schema-fence.md` (no new test nodes).

Executed after the repair:

- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py tests/test_soak_promotion_gates.py -x -q -rs`:
  **102 passed, 5 skipped**. Skips require a migrated `MAISTRO_TEST_PG_DSN`;
  this round does not claim live PostgreSQL validation.
- `uv run python scripts/check-suite-inventory.py --suite packages/maistro-core/tests`:
  **passed**, 12,750 collected and unique identities, no copied-test duplicates.
- `uv run ruff check .`: **passed**.
- `uv run ruff format --check .`: **passed**, 2,883 files.
- In-memory mutation validation via `uv run python` / `pytest.main` removed
  the production advisory-lock call, then separately removed the transaction
  context. The repaired test failed at line 151 and line 143 respectively.
  Both expected-failure assertions passed. Original method restored in memory;
  no production file edits or destructive git operations.
- Executed `preflight_artifact_check()` and evaluated the four frozen historical
  packs through current `failed_promotion_checks`. All four fail both duration
  and exact-RC artifact checks. Round 5 records 90.17 seconds, round 6 90.43;
  the other two omit top-level observed duration. This is rejection validation,
  not a new soak or a re-signing of historical functional summaries.

## Acceptance disposition

| Criterion | Fresh evidence and remaining gap |
| --- | --- |
| Representative release profile | PARTIAL: profile exists, but its remaining-gaps section excludes multi-user/Workspace, fan-out, successful tools/models, Design/Canvas and sustained Goal/background workloads. |
| At least two application replicas | UNVERIFIED on exact RC; middleware tests use two ASGI instances, historical host preflight is not the production artifact. |
| Sustained saturation, queues, reclaim, retries, leaks | UNVERIFIED; all four historical packs fail executed duration evaluation. |
| Exactly-once physical work / Goal reconciliation | UNVERIFIED; admission probes do not execute their scheduled Run; local backpressure test uses an in-memory spine without physical execution. |
| Replica-selection non-bypass / security / degradation | NOT MET for non-bypass: executed real middleware regression gives the same identity [200, 200, 429] on each replica independently, for both identity classes. Other deployment-wide claims UNVERIFIED. |
| Full telemetry and thresholds | UNVERIFIED; driver loop lag is not application loop lag; historical wrapper-only resource measurements are invalid as application observations. |
| Active-work kill/restart fencing/recovery | UNVERIFIED; process exit/rejoin is not physical Attempt recovery correlation. |
| Long soak of exact RC artifact/config | NOT MET; executed evaluator rejects all four packs; host preflight artifact check always false. No exact promotion image/config identified for this round. |
| Findings filed/reclassified | PARTIAL: existing F11/F12 classify M3-A evidence validity locally; external filing UNVERIFIED and forbidden in this lane. The repaired stale assertion was a merge-induced test mismatch, not an observed production concurrency defect. |
| Machine/human hash-bound RC evidence | UNVERIFIED; historical packs exist, but none signs this RC artifact/configuration. |

## Handoff

**BLOCKED for #860 acceptance.** Actual merge-induced test failure repaired;
requested vulture failure does not reproduce. Do not amend a matching ledger or
re-run a short emulator and call it acceptance. Next owner must identify exact
promotion images/configuration, resolve the cross-replica allowance mismatch,
complete the representative workload and telemetry, then execute at least four
hours with physical Attempt recovery correlation. Runtime/config changes require
a new soak.

Changed files: this report, `packages/maistro-core/tests/persistence/test_pg_learnings.py`,
and `docs/testing/inventory-notes/m3a-860-merged-schema-fence.md` only. No runtime,
ledger/grant, historical-evidence, or deployment edits. Local commit follows;
no push or GitHub mutation. Progress: checked 1, done 0, skipped 0, errors 0,
blocked 1; one evidenced test repair completed within the blocked issue.
