# Issue #860 — repair validation 923fa480

## Frozen scope and disposition

Only issue #860 in `auto-860`, starting head
`9eb7cf55a7afac0bc68cc623cdce4d5d97e9b92a`, supplied base
`ac7370141e8e61bd6f352bca35ed0b505104aadb`. Initial worktree clean.
Scope: supplied schema-fence failure, exact vulture scan, existing soak
acceptance probes, and this checkpoint. No other issues/PRs processed.
Candidate implementation files were `pg_learnings.py`, its adjacent test,
`run_soak.py`, `test_soak_promotion_gates.py`, and the explicitly permitted
vulture ledger if the scan required repair. None required an edit.

Read the frozen dispatch issue body, prior result and supplied failed log,
repository instructions, documentation authority hierarchy, and accepted
ADR-081226-a66b and ADR-081626-f383. There are no current-job `check-*.log`
files. Assumption: the prior BLOCKED result concerns missing promotion evidence,
not a develop-sync conflict; no fetch/merge is justified.

## Fresh executed checks

All commands ran in the assigned worktree with 1200-second timeouts:

- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  **37 passed, 6 skipped**. The supplied historical failure no longer reproduces:
  lines 173–175 independently expect all three Gauntlet audit columns inside
  the transaction/advisory-lock fence. Skipped PostgreSQL tests are not live proof.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`:
  **passed**, 1322 reviewed identities / 1322 findings, zero unclassified or
  never-allowlist findings. Arguments match `.github/workflows/vulture-ratchet.yml`.
  No ledger changes warranted by evidence.
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  **73 passed**. Includes production middleware and task-router ASGI probes.
- `uv run ruff check .`: **passed**.
- `uv run ruff format --check .`: **passed**, 3301 files already formatted.
- `uv run python scripts/check-suite-inventory.py`: **passed**, 17 suites,
  31323 unique identities. No tests changed/added; no inventory delta needed.

## Acceptance assessment (not promotion approval)

| Issue criterion | Fresh evidence / remaining requirement |
|---|---|
| Representative workload | UNVERIFIED: inspected `m3a-load-profile.md`; explicitly omits multi-user/Workspace, fan-out, successful model/tool, Canvas and Goal workloads. |
| Two production replicas | UNVERIFIED: executed two-instance ASGI probes, not deployed exact-RC replicas. |
| Sustained saturation, reclaim, retries and leaks | UNVERIFIED: no long production run executed. Sampler tests alone do not prove this. |
| No duplicate physical work; Goal reconciliation | UNVERIFIED: admission-gate tests do not prove physical execution uniqueness or sustained Goal reconciliation. |
| Replica-resistant security/rate/degraded behavior | NOT PROVEN: `test_replica_selection_has_an_independent_production_allowance` passes by observing `[200, 200, 429]` independently on both replicas, with the same credential/IP. |
| Production telemetry and thresholds | UNVERIFIED: application-loop, worker, pool and long-window observations remain absent; driver-loop telemetry is not application telemetry. |
| Active-work kill/restart/drain/fencing/recovery | UNVERIFIED: no production restart performed. |
| Long exact-RC soak, repeated after changes | UNVERIFIED: executed CLI tests reject missing/null/preflight artifact evidence even with a synthetic four-hour duration. `run_soak.py:744` explicitly cannot run the promoted artifact. |
| Finding classification completeness | UNVERIFIED: no new live soak or GitHub mutations; existing local observations are not proof of complete filing. |
| Hash-bound machine/human production evidence | UNVERIFIED: this checkpoint identifies local source checks only, not an RC image/configuration. |

Production inspection corroborates the probes: `api/rate_limit.py:95` constructs
an in-memory limiter per middleware instance, and `api/tasks.py:144` reads the
local task queue. The receipt probe at `tests/test_soak_promotion_gates.py:564`
observed local 200 and peer 404 with a shared canonical admitter. These are
real production-code seams, but not a deployed-production soak.

The ADRs retain `Goal -> Graph -> Run -> NodeRun -> Attempt` authority.
Admission deduplication cannot substitute for physical-work fencing; lease
expiry alone does not authorize a replacement scheduler. No new execution,
authorization, persistence, or event authority is introduced. Process-local
rate budgeting is explicitly documented by its existing owner; it cannot be
silently relabeled as proof of the stronger #860 replica-selection criterion.

## Handoff

**BLOCKED.** Only this checkpoint changed. Both supplied CI repair leads are
already clean; speculative production/ledger changes would not resolve the
actual missing acceptance evidence. No immutable promotion RC image/config
was identified by the assignment, and the existing preflight cannot certify it.
Next: select that artifact/config, settle representative workload and replica
budget/receipt semantics with their canonical owners, then run and publish the
long active-work production soak. Do not repeat a short emulator run as promotion
proof or weaken the artifact gate.

Progress: checked 1 issue, done 0, skipped 0, validation errors 0; acceptance
remains blocked. Existing implementation and historical evidence preserved.
