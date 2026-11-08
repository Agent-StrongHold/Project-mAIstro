# Issue #860 — bounded repair 3267fc52

## Frozen scope

- Issue: #860 only; branch `auto-860`; starting HEAD
  `4995db99985c68fdaa3e292570a1c1e793ffaa39`; supplied base
  `d99e598e1084a183d1280fbe9a2c4de8b50b7f2b`.
- Worktree was clean. No salvage patch needed. No remote mutations permitted.
- Repair candidates: `quality/vulture-baseline.json` only if the required exact
  scan identifies retained debt; `packages/maistro-core/tests/persistence/test_pg_learnings.py`
  and its production module only if the supplied schema failure reproduces;
  `scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py` only for
  reproduced issue-specific defects; this report and an inventory note if tests change.
- Read-only evidence: repository instructions, relevant ADRs, existing load
  profile/evidence, adjacent tests, supplied dispatch context and prior result.
  No other issues or linked PRs will be processed.

## Initial evidence / assumptions

The current job directory has no `check-*.log` files. The supplied prior
`98a11313.../check-3.log` records 24 schema DDL statements versus 21 expected;
this is historical evidence, not a current failure. The supplied prior result
reports an unresolved exact-artifact/production-soak prerequisite. This is not
a develop-sync conflict; no fetch/merge is justified by that evidence.
The base-to-head diff includes substantial inherited unrelated changes; this
round will not overwrite or attempt to reconcile those changes.

## Executed checkpoint

- Required exact vulture scan: PASS, 1,326 findings / reviewed identities,
  zero unclassified or never-allowlist findings. No ledger edit justified.
- Historical schema failure does not reproduce: `uv run pytest
  packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  **37 passed, 6 skipped**. Current test independently expects the three
  validation audit columns missing from the historical expectation. Database
  skips are not live concurrent-DDL proof.
- `uv sync --locked --extra dev`: PASS.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3,195 files.
- `uv run pytest tests/test_soak_promotion_gates.py
  tests/test_prod_stack_boot_contract.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  packages/maistro-server/tests/api/test_rate_limit.py -x -q`:
  **100 passed**.
- `uv run python scripts/check-merge-markers.py`: PASS.

No source/test defect has been reproduced by these commands; do not edit the
ledger or weaken tests to manufacture a CI repair. 

## Architecture and acceptance review

Read repository instructions/documentation map and accepted ADRs
081426-1f7c, 081626-f383, 082526-b36a, and 073126-c4e1. Physical execution
identity is Attempt, lease/fence authority belongs to the canonical store,
and reclamation requires expiry rather than restart-implies-death. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`. Admission-only probes cannot
establish physical-work uniqueness. The immutable release process does not
permit treating a newly built local artifact as the selected RC by assumption.

No deployed load experiment was performed this round. A fresh `uv run python -`
imported the current evaluator and checked the historical round-30 JSON:
420.08 seconds versus 14,400 required; failed checks exactly
`sustain_duration` and `exact_rc_artifact`. Assertions passed. This is a
rejection of historical evidence, not a new soak.

| #860 acceptance criterion | Fresh evidence / disposition |
| --- | --- |
| Representative RC load profile | **UNVERIFIED complete.** `m3a-load-profile.md:145–164` lists missing users/Workspaces, fan-out, successful model/tool, Canvas and Goal workloads. `scripts/soak/run_soak.py:1372–1395` uses one credential and a limited request mix. |
| At least two application replicas | **UNVERIFIED deployed RC.** `deploy/docker-compose.prod.yml:26–77` defines two services; executed boot-contract tests are structural, not deployed load evidence. |
| Sustained saturation, queue growth, lease/retry and leak behavior | **UNVERIFIED.** Current evaluator rejects historical 420.08-second evidence. Sampler tests exercise real child memory/descriptors but not this sustained production criterion. |
| No duplicate physical work, including Goal reconciliation | **UNVERIFIED.** `scripts/soak/run_soak.py:1044–1072` cancels an unexecuted schedule-probe Run. Admission uniqueness is insufficient under the accepted runtime/fencing ADRs. |
| Concurrent rate/security/degraded behavior resists replica selection | **UNVERIFIED overall; independent budgets reproduced.** Executed `tests/test_soak_promotion_gates.py:439–493`: the same identity gets `[200, 200, 429]` on each real middleware instance. `rate_limit.py:32–37` documents that scope. Local security/backpressure tests pass; shared enforcement is not proven. |
| Complete telemetry with explicit thresholds | **UNVERIFIED.** `scripts/soak/run_soak.py:1410–1424` measures driver loop lag, not application event-loop lag. Profile lists outstanding worker/saturation/reclaim/leak evidence. |
| Active-work kill/restart proves drain/fencing/recovery | **UNVERIFIED.** `scripts/soak/run_soak.py:1427–1489` records process/HTTP recovery, not an active-Attempt physical-work oracle; no new kill/restart performed. |
| Long-running exact-RC/configuration soak | **BLOCKED / UNVERIFIED.** Current `preflight_artifact_check()` always returns false (`run_soak.py:730–741`); executed CLI regression tests reject even four-hour synthetic preflight evidence. No selected immutable RC/configuration supplied in the assignment. |
| Findings filed/reclassified before promotion | **UNVERIFIED completeness.** Existing findings are documented, but no complete new load audit was performed; GitHub mutations are prohibited. |
| Machine/human evidence tied to exact image/package/commit/config | **UNVERIFIED current RC.** Historical evidence and this validation note are not a selected-RC evidence pack. |

## Disposition and handoff

**BLOCKED**, not merge-ready. This round changes only this report. No source,
ledger, grant, inventory baseline or test changes; no inventory delta required.
No source repair is justified by the reported historical failure or the current
scanner output. This does not assert the inherited branch is integration-ready.
All commands used long timeouts (1,800 seconds for validation).

Next required input/work: selected immutable RC and configuration, complete
representative production workloads and Attempt-level recovery/telemetry,
resolution of replica-selection semantics, then the required long soak and
fresh hash-bound evidence. Repeating a passing CI scan cannot supply these.
No GitHub mutations or new execution/authorization authority were introduced.

Progress: {checked: 1, done: 0, skipped: 0, errors: 0,
next: exact-RC prerequisites and missing production acceptance evidence}.
This report is committed locally as the checkpoint for the blocked item.
