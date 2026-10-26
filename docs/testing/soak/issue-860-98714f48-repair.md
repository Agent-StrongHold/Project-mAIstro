# Issue 860 repair — job 98714f48

## Frozen scope

Only issue #860, branch `auto-860`, starting HEAD
`0deec723b690d05b3978e75b0ca8204410aa9e5c`, supplied base
`2154f845347c9541016288c760f8da3f5cd2e064`. Worktree initially clean.
No GitHub changes or integration approval.

Process the supplied schema-fence failure and required exact vulture scan as one
repair item. Candidate edit files: this note,
`packages/maistro-core/tests/persistence/test_pg_learnings.py`,
`packages/maistro-core/src/maistro/persistence/pg_learnings.py`,
`docs/testing/inventory-notes/m3a-860-merged-schema-fence.md`, and
`quality/vulture-baseline.json` only if fresh scan evidence requires it.
Inspect existing soak harness/tests, profile, relevant ADRs, repository guidance
and supplied dispatch evidence to assess acceptance; do not expand implementation
into another scheduler, authorization path, or release campaign.

## Initial evidence

The current job directory contains no `check-*.log` files. Supplied prior
`98a11313167b41a98a420abfda80c292/check-3.log` reports an expected-DDL
length mismatch (24 actual versus 21 expected) in the schema-fence test.
The supplied previous result is BLOCKED on missing production RC soak evidence.
These are historical observations, not proof of current behavior.

Ambiguity: the assignment includes both CI repair and production soak acceptance.
Proceed with fresh CI checks and explicit acceptance accounting; do not invent an
RC identity or treat unit tests as production load evidence.

## Results

Fresh required vulture scan passed: 1,323 findings / reviewed identities, zero
unclassified and never-allowlist identities; gate-selected base `3c761d14db94`.
No ledger amendment is supported by the scan.

`uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
passed: 37 passed, 6 skipped (1.48 s). The historical failure no longer reproduces:
the independent expected DDL includes the three audit columns at lines 175–177.
Do not remove production DDL to match a stale failure.

## Completed validation

All commands ran with 1,200-second timeouts:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: PASS as above; matches `.github/workflows/quality.yml:1078` and `vulture-ratchet.yml:82`.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`: 37 passed, 6 skipped; no live PostgreSQL evidence claimed.
- `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs`: 81 passed (2.63 s).
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3,277 files.
- `uv run python scripts/check-doc-links.py`: PASS, 2,705 Markdown files, zero broken relative links.
- `uv run python scripts/check-backlog-consistency.py`: PASS, 168 items.

## Acceptance review

Read the supplied dispatch issue body and prior result, repository instructions,
documentation authority map, current profile, production schema and middleware,
reference Compose topology, and adjacent regression tests. Historical comments,
prior test claims and prior soak outputs do not establish this HEAD's acceptance.

| Issue acceptance criterion | Fresh evidence / disposition |
| --- | --- |
| Representative RC users/Workspaces/request mix/fan-out/schedules/tools/models/Design/Canvas/background profile | **UNVERIFIED**: `m3a-load-profile.md` explicitly lists missing representative workloads. The existing profile is preflight, not a complete selected-RC profile. |
| At least two production application replicas | **UNVERIFIED**: Compose declares two replicas; no exact-RC deployment exercised in this repair. ASGI middleware instances are not deployed applications. |
| Sustained saturation, queue growth, lease reclaim, retry/backoff, leaks, shutdown/restart | **UNVERIFIED**: no sustained production experiment executed. |
| No duplicate physical schedule/task/Run/Attempt work; Goal reconciliation | **UNVERIFIED**: profile's schedule-admission probe cancels the queued Run without physical execution; uniqueness is not execution fencing. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **Not proven**: executed `tests/test_soak_promotion_gates.py:439` reproduces 200/200/429 independently on each middleware instance for the same identity. Production `api/rate_limit.py:94` constructs in-memory state, installed in `main.py:648`. Deployment-level enforcement/security/degraded behavior remains **UNVERIFIED**. |
| Complete required telemetry with thresholds | **UNVERIFIED**: profile distinguishes driver-loop lag from application-loop lag and lacks qualifying saturation/reclaim/long-window observations. |
| Kill/restart during active work proves drain/fencing/recovery | **UNVERIFIED**: no deployed active-work recovery experiment executed. |
| Long-running exact-RC artifact/configuration soak | **UNVERIFIED**: `scripts/soak/run_soak.py:744` returns `ok: False` for host preflight identity at any duration. Promotion-gate regression tests passed; that is not a soak. |
| Findings filed/reclassified before promotion | Existing backlog structure validated; new load findings **UNVERIFIED**. No new load experiment or GitHub mutations. |
| Machine/human evidence bound to exact artifact/configuration hashes | **UNVERIFIED**: no immutable RC image/configuration or qualifying measurements produced in this repair. |

## Architectural reconciliation and disposition

Accepted ADR-082826-b601 requires the canonical consumer and transition claim;
preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`. Admission probes cannot
replace physical-execution proof. Accepted ADR-085 requires principal-keyed
limiting but does not prove shared replica allowances. ADR-081 is **Proposed**,
not accepted authority; the shipped Compose reference still declares two replicas
and explicitly tells deployments to pin image digests. Do not invent a competing
scheduler, store, authorization path, or a release identity to bypass these gaps.

**BLOCKED** on production acceptance, not a reproduced schema/vulture CI defect.
No production/test/ledger edits warranted by the fresh checks. Only this handoff
changes; no tests added and no inventory delta required. Existing work preserved.
Next: supply the selected immutable RC/configuration, complete representative
workloads plus physical-work/recovery/telemetry oracles, resolve the replica-budget
claim, and run the qualifying >=4-hour production soak. A longer host preflight
cannot satisfy the exact-artifact criterion.

Progress: checked 1 issue, acceptance-complete 0, skipped 0 issues, validation
errors 0. Local writer handoff only, not integration approval.
