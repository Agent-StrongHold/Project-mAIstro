# Issue #860 — repair checkpoint fb5da6b7

## Frozen scope

- Only issue #860, branch `auto-860`, starting commit
  `2183892041d5e3fd782d140ec4b2387eb200b2b6`, supplied base
  `ab8b3737fa64f8d840f421ef87ca506c509444ff`.
- Repair targets: evidence-backed vulture identities in
  `quality/vulture-baseline.json` and their source definitions only if the
  requested scan fails. Validate existing `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, and adjacent soak tests. This report is
  the only planned documentation change; no new authority or policy changes.
- Initial worktree clean and HEAD matches dispatch. No salvage needed.
- Current job directory has no `check-*.log` files. Inspect the explicitly
  supplied prior failed check instead; do not infer its failure is current.
- Previous result reports missing production acceptance evidence. Treat it as
  a hypothesis until independently inspecting code and running checks.
- Ambiguity: assignment requests CI repair while issue requires a production
  RC soak. Proceed with focused CI validation, explicitly retaining any
  production acceptance blockers. No release-candidate artifact/configuration
  was designated in this dispatch.

## Results

- Exact requested vulture command passed: 1,322 reviewed identities / 1,322
  findings, zero unclassified and zero never-allowlist findings. No ledger
  amendment is justified.
- Prior `98a113.../check-3.log` was a learnings schema test mismatch (24 DDL
  statements versus 21), not a vulture failure. Current
  `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
  passed: 37 passed, 6 skipped. The historical failure does not reproduce.
- Inspected production artifact gate: `preflight_artifact_check()` explicitly
  rejects host-uvicorn preflight as exact-RC evidence. Four-hour duration alone
  cannot change that conclusion.

- `uv run ruff check .`: passed.
- `uv run ruff format --check .`: passed (3,301 files).
- `uv run pytest tests/test_soak_promotion_gates.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  73 passed. This includes real production middleware instances demonstrating
  independent replica allowances for the same authenticated or unauthenticated
  identity; it does not prove a shared cluster budget.
- Accepted ADR-081426-1f7c assigns physical execution identity to Attempt;
  ADR-081626-f383 assigns fencing authority to the canonical Run store. A
  schedule admission race is not physical execution evidence. The driver
  explicitly cancels its unexecuted probe Run through that store.

- `uv run python scripts/check-suite-inventory.py --suite tests/ --suite
  packages/maistro-core/tests --suite packages/maistro-server/tests`: passed;
  5,291 / 16,361 / 566 collected respectively, no duplicate identities. No
  tests added or changed, so no inventory delta note is required.
- Executed the current `failed_promotion_checks` against the frozen historical
  `docs/testing/soak/evidence/m3a-repair-validation.json` via `uv run python`:
  rejected on task admission, failover, nonterminal Runs, admission
  availability, duration, exact artifact, and graceful drain. That artifact
  has no `sustain_seconds` or `sustain_duration` check; no duration inferred.
- Read accepted recurrence ADR-082126-f69c: schedules produce canonical Runs,
  not a second execution engine. This round neither invents a recovery
  authority nor interprets admission deduplication as physical-work fencing.

## Acceptance accounting

All ten issue criteria were checked against the existing profile/driver/tests.
None is proven at production promotion grade by this round:

| Criterion | Executed evidence / outstanding proof |
|---|---|
| 1. Representative profile | UNVERIFIED: inspected `m3a-load-profile.md`; the single-key degraded-provider mix omits concurrent Workspaces, successful tool/model work, Graph fan-out and Design/Canvas. No selected RC configuration justifies exclusions. |
| 2. At least two production replicas | UNVERIFIED: `run_soak.py:19` explicitly identifies a host-process preflight; ASGI replica tests are not deployment evidence. No production stack launched this round. |
| 3. Sustained saturation/reclaim/leak observations | UNVERIFIED: current evaluator rejects the historical evidence's missing duration gate; no new sustained run executed. |
| 4. No duplicate physical work | UNVERIFIED: `run_soak.py:1070` documents that the schedule probe only admits then cancels an unexecuted Run. Passing admission tests cannot establish Attempt fencing or Goal reconciliation under load. |
| 5. Replica-independent security/rate/degraded enforcement | UNVERIFIED with contrary rate evidence: `test_replica_selection_has_an_independent_production_allowance` passed for both identity classes. Each real middleware instance independently returns 200,200,429 for the same identity. |
| 6. Full production telemetry and thresholds | UNVERIFIED: profile distinguishes driver loop lag from application loop lag and lacks production-grade pool saturation, worker and lease-reclaim observations. No fresh production telemetry collected. |
| 7. Kill/restart during active work with fencing/recovery | UNVERIFIED: boot cleanup and response-accounting tests passed, but no active production Attempt was killed/recovered this round. |
| 8. Long-running exact RC/config soak | UNVERIFIED: four-hour preflight rejection tests passed; `preflight_artifact_check()` returns false. No immutable promotion artifact/config designated or exercised. |
| 9. Findings reclassified to earliest invariant | UNVERIFIED: this note records reproduced contrary evidence, but does not prove a complete production findings disposition. No GitHub mutations performed. |
| 10. Machine/human evidence bound to promoted hashes | UNVERIFIED: existing historical machine evidence is rejected by the current evaluator. This human validation report is not a hash-bound RC soak pack. |

## Handoff

**BLOCKED**, not MERGE-READY. The historical CI failure is already repaired and
vulture needs no ledger change; a cosmetic amendment would not repair the actual
remaining acceptance gap. Only this report changed. Focused validation totals
110 passed, 6 skipped; skipped database cases were not promoted to successes.
No new production soak claim, no gate weakening, no source changes, no
scheduler/store/auth authority changes, and no release authorization.

Progress: checked 1 issue; completed 0; skipped 0; blocked 1; validation errors 0.
Next: designate immutable RC images and normalized production configuration,
implement/use a production-topology runner and representative workload through
the existing canonical spine, then run at least four hours with physical-work
and telemetry evidence. Repeat after any code/runtime-config change. Resolve
the replica-selection allowance claim rather than treating six independent
429 probes as proof of one cluster budget. These are substantive production
work/evidence requirements; rerunning the passing vulture gate cannot close them.
