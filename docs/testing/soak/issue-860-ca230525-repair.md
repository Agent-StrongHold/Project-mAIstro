# Issue #860 — ca230525 repair checkpoint

## Frozen scope

Only issue #860, branch `auto-860`, starting head
`35b51e1628377b1880983e2cb235af57582184cf`, supplied base
`321cbdb8fe9b5a0eacb75deaaa01dad1d12b6f62`.
Starting worktree was clean; no salvage patch needed.
No GitHub mutations, merge, or ref changes are planned.

Review inputs: supplied dispatch-context.json, prior result 20692b05,
prior failed check 98a11313/check-3.log, repository instructions, relevant
ADRs, existing soak runner/profile/promotion tests and production rate limiter.
Permitted edit scope: this checkpoint; quality/vulture-baseline.json and
source identities only if the required fresh scan demonstrates actionable debt.
No new test is planned without a demonstrated repair and inventory note.

The current job directory contained no check-*.log at initial inspection.
Assumption: this is the writer lane; execute fresh checks rather than rely on
prior verification claims. The prior BLOCKED result is evidence to recheck,
not permission to claim completion or replace the production execution path.

## Fresh results

- Required exact vulture scan: PASS, 1322 reviewed identities / 1322 findings,
  zero unclassified and never-allowlist findings. No ledger amendment justified.
- Historical check-3.log was a schema-fence test failure (24 DDL statements vs
  21 expected), not a vulture failure.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  37 passed, 6 skipped. Historical failure does not reproduce at the assigned head.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3301 files.

- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q`:
  99 passed, including both same-identity replica-selection probes and the
  exact-artifact fail-closed CLI checks.
- `git diff --check`: PASS.

Commands used 1200-second timeouts. Total: 136 passed, 6 skipped. No production
soak or gate repair has been claimed. No tests changed or added; no inventory
note delta is required.

## Architecture and evidence

Read accepted ADR-081226-a66b, ADR-081426-1f7c, ADR-081626-f383, and
ADR-085. Preserve Goal -> Graph -> Run -> NodeRun -> Attempt. In particular,
the lease ADR does not yet authorize expiry takeover: do not invent recovery
or competing execution authority to satisfy the issue's reclaim criterion.

The production app installs `RateLimitMiddleware` at
`packages/maistro-server/src/maistro_server/main.py:648`. Its constructor at
`api/rate_limit.py:93` creates an `InMemoryRateLimiter` per instance. The
executed regression at `tests/test_soak_promotion_gates.py:439` observes
`[200, 200, 429]` independently on two instances, for the same authenticated
principal and separately for the same unauthenticated IP. This is actual
production-middleware seam evidence, not deployed multi-replica traffic.
The documented N-times local-budget behavior is not evidence for #860's
stronger replica-selection-resistant acceptance requirement.

The executed production task-router probe at
`tests/test_soak_promotion_gates.py:569` observes a peer-local receipt 404.
Its shared admission spine does not prove successful distributed physical work.
The host-process runner's `preflight_artifact_check` at
`scripts/soak/run_soak.py:744` always returns `ok=false`; the CLI regressions
reject missing, null and preflight artifact records even for a simulated
four-hour run. There is no basis to run another emulator smoke and call it RC
promotion evidence.

## Acceptance disposition

| #860 criterion | Evidence / disposition |
| --- | --- |
| Representative RC profile | UNVERIFIED: `m3a-load-profile.md:169` explicitly retains user/Workspace, fan-out, successful tool/model, Design/Canvas and Goal/background-work gaps. No selected immutable RC configuration is supplied in the assignment. |
| At least two deployed replicas | UNVERIFIED: two ASGI middleware instances are not deployed application replicas. No deployed run executed this round. |
| Sustained saturation, queue growth, lease reclaim, retries and leaks | UNVERIFIED: targeted tests are short and six database-dependent cases skipped; no long production time series. |
| No duplicate physical schedule/task/Run/Attempt/Goal work | UNVERIFIED: observed admission identity tests do not prove physical execution uniqueness. |
| Replica-selection-resistant rate/security/degraded behavior | NOT SATISFIED at the tested rate-limit seam: independent allowances demonstrated. Other deployed security/degraded behavior remains UNVERIFIED. |
| Complete telemetry with explicit thresholds | UNVERIFIED: no fresh PostgreSQL contention/query, application-loop, worker/process, RSS/FD, queue or error/timeout series. Driver loop measurements cannot stand in for application-loop latency. |
| Kill/restart during active work with drain/fencing/recovery | UNVERIFIED: no physical replica kill during real work; retryable admission backpressure tests are not recovery evidence. |
| Long exact-RC soak | UNVERIFIED: current runner explicitly fails artifact equivalence, and no immutable RC image/config was selected. |
| Findings filed/reclassified to earliest broken invariant | UNVERIFIED for completeness. Replica-local budgets and peer receipt visibility are correctness prerequisites, not throughput optimization; recorded locally, no GitHub mutations. |
| Machine/human soak evidence bound to exact hashes | UNVERIFIED: this handoff identifies source HEAD but is not a production soak or an image/package/configuration evidence bundle. |

## Handoff

BLOCKED. Only this report changed. No source, test, ledger, grant or gate edits;
no develop-sync conflict exists. The historical failed command is already fixed
at the supplied starting head; the fresh exact-debt scan leaves no actionable
identity to bank or remove. Changing a synchronized ledger would be cosmetic.

Next: provide/select the immutable RC deployment and workload applicability;
resolve replica-local enforcement and receipt visibility through existing
production seams, then execute the long supported-topology soak with physical
work/recovery observations and complete telemetry. Do not re-dispatch the same
passing vulture/schema checks as a repair without new failure evidence.

Progress: checked 1 issue; done 0 acceptance-complete; skipped 0 issues;
validation errors 0; next: production prerequisites above. This is a local
writer handoff, not integration approval.
