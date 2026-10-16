# Issue #860 repair checkpoint — 0843e211

## Frozen scope

- Assigned issue: #860 only; branch `auto-860`.
- Starting HEAD: `2fc05476e9f25ad99698202829dd83de9b5b5c3f` (clean).
- Supplied base: `321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`.
- Inspect supplied dispatch evidence, existing soak runner and tests, relevant ADRs,
  and the exact vulture gate. Amend only evidenced retained ledger identities or
  focused soak defects; no unrelated production repairs or GitHub mutations.
- Current job contained no `check-*.log` files at initial inspection. Prior
  results are leads, not proof.
- Assumption: this is a writer CI-repair round, not a verifier-only assignment.
- Initial broad instruction-file search accidentally included sibling paths;
  no sibling file contents were inspected or changed. Further work is confined
  to this worktree and supplied job evidence.

## Executed checkpoint

- Exact prescribed vulture scan: PASS, 1322 findings / 1322 reviewed identities,
  zero unclassified, zero never-allowlist. No ledger change is justified.
- Focused tests (schema fence, task backpressure, soak promotion gates, production
  boot contract): 118 passed, 6 skipped in 2.37s. The supplied historical
  `98a113.../check-3.log` schema assertion failure does not reproduce.
- No new tests or production changes; inventory delta is not needed.

## Validation commands

Executed with 1200-second timeouts; all returned success:

```text
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q
uv run ruff check .
uv run ruff format --check .
uv run python scripts/check-deployment-claims.py
uv run python scripts/check-compose-secrets.py
uv run python scripts/check-merge-markers.py
uv run python scripts/check-suite-inventory.py
```

Formatting checked 3301 files. Inventory matched 17 suites / 31323 unique
identities; inventory collection is not execution of those suites. No full
package suite or live deployment soak was run. The schema regression now
independently expects all three validation audit columns at
`packages/maistro-core/tests/persistence/test_pg_learnings.py:175-177`.

## Architecture and acceptance audit

Read accepted ADR-081426-1f7c and ADR-082526-b36a. Physical work belongs to
canonical Attempts; Runtime owns mechanics, and recovery uses fenced leases
and heartbeat renewal, not restart-implies-death. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`; no replacement execution,
authorization, or recovery authority was introduced.

The following audits the ten acceptance bullets in the supplied frozen issue
body. Historical evidence is not a fresh exact-RC soak.

| Criterion | Current evidence / disposition |
|---|---|
| Representative RC profile | UNVERIFIED: `m3a-load-profile.md` explicitly leaves concurrent users/Workspaces, Graph fan-out, successful model/tool calls, Design/Canvas and background-worker scope incomplete. |
| Two deployed replicas | UNVERIFIED: executed tests use two ASGI instances, not deployed RC replicas. |
| Sustained saturation, queue growth, reclaim, retry and leaks | UNVERIFIED: focused tests ran for 2.37 seconds; no sustained live run performed. |
| No duplicate physical work | UNVERIFIED: admission counters are not physical Attempt execution observations. ADR requires the canonical Attempt boundary. |
| Replica-selection-resistant rate/security/degraded behavior | UNVERIFIED at promotion scope; executed `test_replica_selection_has_an_independent_production_allowance` (both auth cases) reproduces two accepted requests then 429 independently on each instance. Production `rate_limit.py:32-37` documents N-times aggregate limits. This is a mismatch with a shared-budget interpretation, not an undocumented local implementation defect. Reconciliation remains required. |
| Full telemetry with thresholds | UNVERIFIED: profile defines thresholds but no fresh application-loop, worker/pool/reclaim or long-window telemetry was collected. Driver-loop metrics are not application-loop metrics. |
| Active-work kill/restart, drain/fencing/recovery | UNVERIFIED: not executed live. `test_receipt_load_reads_admitted_tasks_through_production_router` reproduces owner 200 / peer 404 via `tasks.py:144-146`; missing visibility does not by itself establish physical loss or duplication. |
| Long exact-RC artifact/configuration soak | UNVERIFIED: `scripts/soak/run_soak.py:744` explicitly returns failed artifact equivalence for its host-uvicorn topology. Extending this runner to four hours cannot satisfy the criterion. Immutable RC selection remains unresolved. |
| Findings classified to earliest broken milestone | UNVERIFIED for external completeness. This report separates stale CI failure, local admission/visibility limits, and missing release evidence; no GitHub mutations performed. |
| Machine/human evidence bound to exact hashes | UNVERIFIED: this report identifies the tested source commit but is not a machine-readable exact-image/configuration production soak. |

## Handoff / stop condition

**BLOCKED.** Only this report changed; inherited work is preserved. No vulture
identities are missing and the cited historical test failure does not reproduce,
so there is no evidenced CI repair to apply. No tests were added or changed;
no inventory note or ledger/grant edit is warranted.

Before another acceptance attempt: select immutable RC images and normalized
production configuration, resolve supported workload scope and model gateway,
provide a production-topology runner with physical Attempt and application
telemetry observations, and resolve the rate-budget/receipt-visibility findings.
Then execute the >=4-hour exact-RC soak with active-work interruption. A repeated
CI-only repair against this unchanged implementation cannot supply that proof.
No develop-sync conflict was present; no fetch/merge was needed.

Checkpoint: checked 1 issue; done 0 acceptance-complete issues; skipped 0;
validation errors 0; next: RC prerequisites and production soak. Commit this
handoff locally; no integration approval or issue closure is implied.
