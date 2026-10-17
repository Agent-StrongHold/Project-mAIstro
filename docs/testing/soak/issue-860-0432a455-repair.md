# Issue #860 — repair checkpoint 0432a455

## Frozen scope and initial evidence

- Assigned issue: #860 only; branch `auto-860` in the assigned worktree.
- Starting HEAD: `0dbc70e202556b7d20a09be08c82309d7970e8f2`.
- Supplied base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Worktree initially clean; no salvage or merge conflict present.
- Editable snapshot: this report and `quality/vulture-baseline.json` only if
  the mandated scan produces actual reviewed retained identities. No test,
  production, grant, or unrelated issue changes planned.
- Role ambiguity: proceed as writer, as explicitly assigned by the lane.
- No `check-*.log` files exist in the current job's initial directory listing.
  Read the supplied prior `98a113.../check-3.log`: it reports a schema-fence
  assertion (24 DDL statements versus 21 expected), not a Vulture failure.
- Fresh exact Vulture command passed: 1323 findings and 1323 reviewed identities,
  zero unclassified/never-allowlist findings. No ledger edit is justified.

## Fresh validation

All commands below executed with 1200-second timeouts:

```text
uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'
uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py -x -q
uv run ruff check .
uv run ruff format --check .
```

Results: Vulture passes; pytest **126 passed, 6 skipped in 3.17s**; Ruff lint
passes; Ruff format reports **3277 files already formatted**. Skips are not
acceptance evidence. No new tests or inventory-count changes in this pass.
`uv run python scripts/check-doc-links.py` also passed (2692 Markdown files,
zero broken relative links); `git diff --check` passed. No command failed.

The prior schema-fence failure is already repaired: the independent expected
DDL list at `packages/maistro-core/tests/persistence/test_pg_learnings.py:177`
includes the three validation-audit columns. Its fresh passing assertion
covers the production transaction/advisory-lock boundary at
`packages/maistro-core/src/maistro/persistence/pg_learnings.py:215`.

## Architecture and acceptance evidence

Read repository instructions, documentation authority map, accepted
ADR-081226-a66b, ADR-082526-b36a, ADR-082826-08f0 and ADR-085, the existing load
profile, production schema fence/rate middleware/task routes and adjacent tests.
No change to Goal -> Graph -> Run -> NodeRun -> Attempt, execution authority,
recovery disposition, canonical event stream or authorization is proposed.
Renewal/reclaim and physical-work fencing must be tested at their canonical
seams; queue receipt state cannot substitute for lifecycle state.

| #860 acceptance criterion | Executed evidence / disposition |
| --- | --- |
| Representative RC load profile | **UNVERIFIED**. `docs/testing/soak/m3a-load-profile.md` explicitly lacks multiple users/Workspaces, Graph fan-out, successful tools/models, Design/Canvas and sustained Goal reconciliation. |
| At least two production application replicas | **UNVERIFIED**. ASGI tests execute production middleware/router instances, not the deployed RC topology. |
| Sustained saturation, queue growth, reclaim, retry/backoff and leaks | **UNVERIFIED**. Sampler/accounting regression tests pass, but no sustained production run was executed. |
| No duplicated physical work across schedules/tasks/Run/Attempt/Goal | **UNVERIFIED**. The receipt test at `tests/test_soak_promotion_gates.py:564` uses canonical admission and observes owner 200 / peer 404; it does not execute physical work. Production reads the local queue at `packages/maistro-server/src/maistro_server/api/tasks.py:144`. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **UNVERIFIED**, with contrary evidence for a shared allowance: `tests/test_soak_promotion_gates.py:439` passes by observing 200/200/429 independently on both production limiter instances for the same identity. Production documents process-local state at `packages/maistro-server/src/maistro_server/api/rate_limit.py:32`. Backpressure tests prove retryable 429 at the canonical admission ceiling, not cluster-wide request limiting. |
| Complete required metrics with thresholds | **UNVERIFIED**. Profile documents partial telemetry; driver-loop lag is not application-loop latency. No full production pool/worker/lock/leak series captured. |
| Kill/restart during active work with drain/fencing/recovery | **UNVERIFIED**. Boot/cleanup tests pass; no production active-work recovery experiment executed. |
| Long-running exact-RC soak | **UNVERIFIED**. `scripts/soak/run_soak.py:744` always rejects preflight artifact identity. Executed four-hour-preflight regression tests prove it cannot sign promotion evidence. No immutable RC image/config designated in the lane assignment. |
| Findings filed/reclassified before promotion | **UNVERIFIED**. No new live-load findings claimed; GitHub mutations prohibited and not performed. |
| Machine/human soak evidence tied to exact artifact/config hashes | **UNVERIFIED**. This report identifies the source checked, not an RC image/config soak. |

ADR-085 requires principal-keyed limiting; it does not provide evidence of a
shared cluster allowance. The issue's stronger replica-selection requirement
must be reconciled explicitly, not silently waived based on local enforcement.
Accepted lifecycle/recovery ADRs remain authoritative; no competing scheduler,
store, authorization path or recovery mechanism is justified by this repair.

## Handoff

**BLOCKED** on production acceptance prerequisites, not a reproducible CI gate
failure. Only this report changes. Ledger amendment is conditional on actual
findings; the exact scan provides none to amend. No speculative production fix
or cosmetic scanner repair is appropriate. Existing work is preserved.

Next: designate the immutable RC and production configuration, complete the
representative workload and physical-execution observations, reconcile the
replica-selection rate contract, then run and publish the >=4-hour exact-RC
soak. Repeating this passing CI-repair round cannot satisfy those requirements.

Progress: checked 1 issue, done 0, skipped 0, validation errors 0. Local commit
is a handoff checkpoint, not integration approval.
