# Issue #860 — repair snapshot (215f8d92)

Scope frozen: issue #860, branch auto-860, starting HEAD
17c6b1dcd7014c220d268b23a5c2c501acc17ad1, supplied base
9bd1a93eefc4e564041b3cc512f20b229cde64b9. Initial worktree clean.
No GitHub mutations or new enumeration. Supplied dispatch context is evidence only.

Review scope: repository instructions and relevant execution/deployment ADRs;
prior check-3.log and result.json; existing scripts/soak/run_soak.py,
tests/test_soak_promotion_gates.py, docs/testing/soak/m3a-load-profile.md,
docs/testing/soak/m3a-soak-evidence.md and cited evidence; exact vulture gate,
quality/vulture-baseline.json only if the actual scan requires retained identities.
Production adjacent review: pg_learnings.py and tasks.py with their changed tests.
Only evidence-backed repairs, associated inventory notes if tests change, and this
validation report will be edited. No RC identity or topology will be invented.

Ambiguity: assignment is a writer CI-repair round, not a verifier-only round.
The current job directory has no check-*.log at snapshot time; inspect supplied
prior log and execute fresh checks. Exact release-candidate identity/configuration
must be established before any claim of acceptance.

## Fresh results

- Supplied prior check-3.log failed `test_ensure_schema_fences_ddl_behind_advisory_lock`
  (24 actual statements versus 21 expected). Fresh targeted execution passes:
  `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
  → 37 passed, 6 skipped. The historical failure is not reproduced.
- Exact requested vulture command:
  `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  → exit 0; 1332 reviewed identities / 1332 findings, unclassified 0,
  never_allowlist 0. No evidence justifies a ledger amendment or dead-code repair.
- Supplied prior result is BLOCKED on RC artifact/profile evidence, not a merge
  conflict. No fetch/merge is required by the conditional sync instruction.

- `uv run ruff check .` → pass.
- `uv run ruff format --check .` → pass, 3105 files already formatted.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`
  → 73 passed. Includes actual production rate middleware through ASGI, actual
  task router/admission spine backpressure, and a live subprocess sampler; not
  a production multi-replica traffic soak.
- `uv run python scripts/check-suite-inventory.py` → all 17 suites match;
  28173 unique identities, no duplicate evidence.
- `uv run python scripts/check-backlog-consistency.py` → pass, 168 items.

Architecture reconciliation: ADR-081226-69ee (Accepted) keeps the canonical
Graph/Run/NodeRun/Attempt execution model. ADR-081626-f383 (Accepted) makes the
Run store the lease/fencing authority and explicitly does not define expiry
takeover. A schedule admission race is not physical-execution recovery proof.
ADR-085 (Accepted) requires per-principal request limiting; independent process
allowances cannot establish #860's replica-selection non-bypass criterion.
ADR-081 deployment topology is Proposed, not an accepted waiver of the issue's
exact-artifact requirement. No competing authority or changed policy is added.

- Executed the current `failed_promotion_checks` evaluator against preserved
  `evidence/m3a-round6-shakedown.json`: observed duration 90.43 seconds,
  git head b31c5fdaa63b40506335bbb288889e87bdb9ba0c, failed gates exactly
  `sustain_duration` and `exact_rc_artifact`. Also executed/asserted that
  `preflight_artifact_check()` returns false. Historical evidence was not edited.
- `git diff --check` → pass.

## Acceptance disposition (all ten criteria)

| Criterion | Executed evidence / remaining gap |
| --- | --- |
| Representative RC profile | Reviewed `m3a-load-profile.md`; explicitly missing concurrent users/Workspaces, fan-out, successful tools/models, Canvas/Design and sustained Goal/background workloads. Complete RC applicability UNVERIFIED. |
| At least two production replicas | Two ASGI middleware instances exercised by passing tests, not two deployed RC application replicas. Production run UNVERIFIED this round. |
| Sustained saturation, queue/reclaim/retry/leaks | Live subprocess sampler regression passes. No sustained RC load was executed; acceptance UNVERIFIED. |
| No duplicated physical work | Task backpressure uses real router/spine; HTTP admission oracle cases pass. Neither proves physical Attempt deduplication/reclaim or Goal reconciliation under multi-replica load. UNVERIFIED. |
| Rate/security/degraded non-bypass | `tests/test_soak_promotion_gates.py:439-488` executes production middleware and observes `[200,200,429]` independently on both replicas for the same authenticated or unauthenticated identity. Cluster non-bypass NOT MET; other sustained security/degradation coverage UNVERIFIED. |
| Complete telemetry and thresholds | Live process-group sampler regression passes; `run_soak.py:1523-1585` records selected admission/recovery/resource checks. Application event-loop latency, full pool/worker/leak/error thresholds under the RC are UNVERIFIED. |
| Active-work kill/restart and fencing | Boot/cleanup and gate tests pass; no real active-work kill/restart with correlated Attempts was executed. UNVERIFIED. |
| Long-running exact RC soak | NOT MET: `run_soak.py:686-697` rejects host-process artifact equivalence. Current evaluator rejects the preserved 90.43-second preflight. No exact #89 RC image/config identity was assigned for a new promotion run. |
| Findings filed/reclassified | Existing human evidence classifies F1–F12 and backlog consistency passes. External filing/completeness UNVERIFIED; GitHub mutations prohibited. |
| Hash-bound machine and human evidence | Historical JSON and human pack exist; inspected JSON names an older commit/config, not the assigned head or an exact RC image. Current promotion evidence UNVERIFIED. |

## Handoff / stop condition

Verdict: **BLOCKED**, not integration approval. This round changes only this
report; no code, runtime configuration, ledger, tests or inventory counts changed.
No inventory note is needed. The old schema-test mismatch is already repaired
(the expected SQL list includes all three evaluator audit columns), and vulture
is exactly balanced, so speculative source/ledger changes would be inappropriate.

Next requires release-owner selection of immutable RC image/config identities,
a representative production-topology workload runner with physical Attempt and
security/recovery oracles, resolution of the per-process rate-budget mismatch,
and a fresh >=4-hour soak after all runtime changes. Longer execution of this
host-process preflight cannot remove the artifact blocker. Do not repeatedly
retry this CI-repair lane for the same already-passing historical check.

Progress: {checked: 1, done: 0, skipped: 0, errors: 0, next: release prerequisites}.
Focused CI verification is complete; issue acceptance remains blocked. Finalize
this evidence in a local commit and leave the worktree clean.
