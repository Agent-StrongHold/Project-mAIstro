# Issue #860 — isolated repair checkpoint

## Frozen scope

- Issue #860 only; worktree `/home/dev/Git/wt/auto-860`, branch `auto-860`.
- Starting HEAD `067b3d57b9b1807a21bd591e02ea7c3f26b7d745`; supplied base
  `2154f845347c9541016288c760f8da3f5cd2e064`. Both resolve locally.
- Initial worktree clean; no incoming edits to salvage.
- Input snapshot: job `0efcef84223a4797be413ce7c668f299` dispatch context,
  prior result `8de889e2d7224e9fb92dcf2e3612370c/result.json`, prior failed
  `98a11313167b41a98a420abfda80c292/check-3.log`.
- Inspect only #860 soak runner/profile, adjacent soak and task-backpressure
  tests, relevant ADRs, CI gate implementation/configuration, and any identities
  actually reported by the mandated vulture command. Candidate edits limited to
  this report and evidence-backed vulture fixes/ledger amendments (plus tests
  and inventory notes only if needed).
- Job directory has no `check-*.log` files at initial inspection. Prior results
  are evidence to investigate, not current validation.
- Supplied base-to-HEAD diff includes extensive inherited divergence outside
  #860. Do not revert, merge, or repair unrelated work. No sync conflict exists.

## Ambiguity and assumption

The lane is a writer repair, not a read-only verifier. The explicit vulture
ledger exception applies only to actual reviewed scanner findings. No arbitrary
ledger changes or grant changes will be made. Production acceptance remains
unverified until fresh evidence demonstrates it; no endpoint/image identity is
inferred from historical reports.

## Results

Fresh exact vulture scan PASS: 1,323 findings / reviewed identities, zero
unclassified or never-allowlist identities (gate-selected base `3c761d14db94`).
No evidence warrants a ledger amendment.

Historical `check-3.log` reports 24 schema DDL calls versus 21 expected. Current
schema-fence test already explicitly includes the three validation audit columns
at lines 175–177. Fresh scoped schema suite: **37 passed, 6 skipped** (PostgreSQL
DSN not configured); the historical failure does not reproduce.

Fresh task-backpressure, soak-promotion and production-boot contract suites:
**81 passed**. These are regression checks, not a production soak. The frozen
issue body contains ten acceptance criteria; the profile explicitly documents
missing representative workloads and says host preflight cannot sign promotion.
No production/test change is justified by the historical CI finding.

## Executed validation

All commands ran in the assigned worktree with 1,200-second timeouts (initial
identity/status checks used 120 seconds). All commands below exited successfully:

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  — 1,323 reviewed identities, no new debt. Arguments match
  `.github/workflows/quality.yml:1078–1081`.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q -rs`
  — 37 passed, 6 skipped, 1.58 seconds. Skips require `MAISTRO_TEST_PG_DSN`;
  no live database/schema-race validation claimed.
- `uv run pytest packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py -x -q -rs`
  — 81 passed, 2.49 seconds.
- `uv run ruff check .` — PASS.
- `uv run ruff format --check .` — PASS, 3,277 files.
- `uv run python scripts/check-doc-links.py` — PASS, 2,707 Markdown files.
- `uv run python scripts/check-backlog-consistency.py` — PASS, 168 items.

## Architecture and reachable behavior

Read `AGENTS.md`, the documentation authority map, the supplied issue body,
profile and adjacent tests, and ADR-082826-b601, ADR-085 and ADR-081.
ADR-082826-b601 is Accepted: execution must use the canonical consumer and
transition claim, preserving `Goal -> Graph -> Run -> NodeRun -> Attempt`.
Admission uniqueness is not proof of physical execution uniqueness. The soak
schedule probe explicitly cancels without executing (`run_soak.py:1070–1091`).
No competing scheduler, store, event or authorization authority is introduced.

ADR-085 is Accepted and requires principal-keyed rate limiting. The production
middleware constructs process-local state (`api/rate_limit.py:93`), and
`main.py:648` installs it. The executed test at
`tests/test_soak_promotion_gates.py:439` sends the same authenticated or anonymous
identity to two middleware instances: **200, 200, 429 on each**. Local enforcement
is proven; a shared replica-independent budget is not. This is an unresolved
acceptance/deployment-policy gap, not permission to invent another auth path.
ADR-081 is Proposed and cannot waive the issue's production requirements.

`run_soak.py:1579` wires `preflight_artifact_check()` into actual result generation;
that check returns false at line 744 onward. The executed CLI regression at
`tests/test_soak_promotion_gates.py:106` proves even otherwise-passing four-hour
preflight evidence exits 1. This guards against false promotion, but does not
provide a production runner or a production soak.

## Acceptance accounting (all ten criteria)

| Criterion | Current evidence and disposition |
| --- | --- |
| Representative RC workload profile | **UNVERIFIED**. Existing profile lists gaps in concurrent users/Workspaces, Graph fan-out, successful tool/model calls, Design/Canvas and Goal/background work. No selected RC workload was executed. |
| Two production application replicas | **UNVERIFIED**. Middleware instances in tests are not deployed production replicas; no production topology was exercised in this round. |
| Sustained saturation, queues, lease reclaim, retries, leaks and restart | **UNVERIFIED**. Focused regressions are not sustained production observations. |
| No duplicate physical schedule/task/Run/Attempt work and Goal reconciliation | **UNVERIFIED**. Probe admission/cancellation cannot establish physical-work fencing or Goal reconciliation. |
| Rate/security/degraded non-bypass under replica selection | Independent local allowances reproduced by the production-middleware regression. Deployment-level non-bypass and security/degraded behavior remain **UNVERIFIED**. |
| Complete telemetry with pass/fail thresholds | **UNVERIFIED**. No qualifying PostgreSQL, application event-loop, pool saturation, worker, RSS/descriptor, queue or timeout series captured here. Driver-loop lag is not application-loop lag. |
| Kill/restart during active work; drain/fencing/recovery | **UNVERIFIED**. No active-work production recovery experiment executed. |
| Long-running exact-RC artifact/configuration soak | **UNVERIFIED**. Existing runner rejects its host topology; four-hour minimum alone cannot establish artifact equivalence. |
| Load findings filed/reclassified before promotion | Backlog consistency PASS; completeness of new production load findings **UNVERIFIED**, because no new production load experiment ran. No GitHub mutations. |
| Machine/human evidence bound to exact image/package/commit/config hashes | **UNVERIFIED**. This report identifies local source validation only; it is not an immutable production artifact/configuration evidence bundle. |

## Disposition and handoff

**BLOCKED**, not merge-ready. Only this report changes; tests, production code,
ledgers and grants remain untouched. No test additions, hence no inventory delta.
Inherited history is preserved and was not certified by this focused review.

To unblock: select and supply the immutable RC image/configuration and supported
workload contract, provide production-path workload/recovery/telemetry oracles,
resolve the replica-selection budget claim, and execute a qualifying exact-RC
soak with hash-bound raw and human evidence. Re-dispatching the same schema log
or rerunning a longer host preflight cannot resolve those missing inputs.

Progress: checked 1 issue; acceptance-complete 0; skipped 0 issues; command
errors 0. Historical CI repair checked and already resolved; production acceptance
still blocked. Next: production evidence work above, not speculative CI edits.
This local commit is a writer handoff only, never integration approval.
