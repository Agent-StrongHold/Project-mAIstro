# Issue #860 repair — job 2ed8bf3d

## Frozen scope

Only issue #860 in `/home/dev/Git/wt/auto-860`, branch `auto-860`, starting
HEAD `5dbdf1f3b3eeebab1af54dff75c5c1507a775e67`, supplied base
`ac7370141e8e61bd6f352bca35ed0b505104aadb`. Initial worktree clean.
No GitHub mutations, ref updates, or additional issues are in scope.

Files selected for inspection: repository instructions and architecture/soak ADRs,
`scripts/soak/`, `tests/test_soak_promotion_gates.py`, the supplied dispatch
snapshot and prior failure logs, and `scripts/check-vulture-baseline.py` with its
CI configuration. Candidate edits are restricted to evidence-backed #860 repairs,
`quality/vulture-baseline.json` if the explicitly requested scan requires reviewed
identity changes, accompanying tests/inventory notes, and this handoff.

## Initial evidence and assumptions

- No `check-*.log` files exist in the supplied current job directory.
- Supplied prior result reports BLOCKED, not acceptance completion. Its claims
  will be checked independently; no earlier soak evidence is assumed current.
- Writer role applies (explicit repair assignment); no verifier-only tree edits.
- Exact RC artifact/configuration is not supplied in the lane brief. Do not infer
  RC equivalence from local ASGI tests or synthetic workload success.

## Reproduced validation

- Requested exact vulture command completed successfully: 1,322 findings,
  1,322 reviewed identities, zero unclassified/never-allowlist findings. No
  evidence supports changing the ledger; it remains untouched.
- Prior `98a113.../check-3.log` failed the learnings-schema fence test with
  24 DDL calls versus 21 expected. Fresh command
  `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
  passes: 37 passed, 6 skipped. The supplied failure does not reproduce at this
  starting HEAD; no speculative schema/test changes are warranted.

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS (3,301 files).
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  PASS (73 tests). These freshly reproduce independent per-replica rate
  allowances and peer receipt 404s through production middleware/router seams.
  They also prove the CLI rejects synthetic four-hour preflight evidence; they
  do not prove deployed multi-replica behavior under sustained traffic.
- Profile inspection explicitly identifies missing representative traffic,
  exact-artifact deployment, application-loop telemetry and physical-work
  recovery. It requires at least four hours; host preflight cannot certify it.

- `uv run python scripts/check-backlog-consistency.py`: PASS (168 items).
- `uv run pytest packages/maistro-core/tests/runs/test_execution_fencing.py packages/maistro-core/tests/graph/durable_runs/test_recovery_disposition.py -x -q`:
  PASS (20 tests). Canonical fencing/recovery unit coverage, not production
  active-work crash evidence.

All validation commands used 1,200-second tool timeouts. Total targeted tests:
130 passed, 6 skipped; no full-tree pytest or production deployment was run.
The vulture invocation matches `.github/workflows/vulture-ratchet.yml:82`.

## Architecture reconciliation

Read repository instructions, documentation authority map, accepted
ADR-081426-1f7c and ADR-081626-f383, and the profile's deployment ADR-081.
The latter is Proposed, not an accepted override. Preserve
`Goal -> Graph -> Run -> NodeRun -> Attempt`: ExecutionRuntime owns mechanics,
with Attempt identity; the canonical Run store owns fencing authority.
ADR-081626-f383 explicitly does not define lease-expiry takeover of a live
Attempt. The issue's reclaim acceptance needs a supported contract assessment;
it cannot authorize a new scheduler or implicit takeover policy in this lane.

## Acceptance assessment (fresh checks, not inherited verification)

| Criterion | Evidence and status |
|---|---|
| Representative RC load profile | **UNVERIFIED**. Read `docs/testing/soak/m3a-load-profile.md`; its remaining-gaps section excludes multi-user/Workspace traffic, fan-out, successful tools/models, Design/Canvas and Goal/background reconciliation without a selected-RC applicability assessment. |
| At least two production application replicas | **UNVERIFIED**. Executed two-instance ASGI probes only, not deployed production replicas. |
| Sustained saturation, queue growth, reclaim, retry/backoff and leaks | **UNVERIFIED**. No sustained run this round; local sampler tests are not long-window evidence. Reclaim authority requires the ADR reconciliation above. |
| No duplicate physical work; schedule/task/Run/Attempt/Goal safety | **UNVERIFIED**. Fencing unit tests pass, but `scripts/soak/run_soak.py:1067` cancels the queued schedule probe without executing physical work. No sustained Goal workload. |
| Replica-resistant rate/security/degraded behavior | **UNVERIFIED** overall, with counterevidence to a shared budget: executed `tests/test_soak_promotion_gates.py:439` observes `[200, 200, 429]` independently on both middleware instances for the same identity. Production installs that middleware at `packages/maistro-server/src/maistro_server/main.py:648`; `api/rate_limit.py:32` explicitly documents process-local allowances. This is not proof of a deployed ingress bypass or broader security failure. |
| Production telemetry with explicit thresholds | **UNVERIFIED**. Profile thresholds and sampler tests exist, but no fresh production PostgreSQL/application-loop/worker/resource/queue/error series. Driver-loop lag cannot stand in for application-loop lag. |
| Active-work kill/restart, drain, fencing/recovery | **UNVERIFIED**. Unit checks are not active-work experiments. Executed `tests/test_soak_promotion_gates.py:564` observes receipt 200 locally and 404 on the peer via the production router; `packages/maistro-server/src/maistro_server/api/tasks.py:144` reads the local queue. |
| Long soak of exact RC artifact/configuration | **UNVERIFIED**. `scripts/soak/run_soak.py:744` rejects host-preflight equivalence. Executed CLI regressions reject synthetic four-hour evidence with absent/null/preflight artifact records. No immutable RC image/effective configuration was designated in the assignment. |
| Findings classified to earliest broken milestone | **UNVERIFIED** for completeness. Backlog consistency passes, but no new production experiment or complete findings classification was performed. GitHub mutations remain prohibited. |
| Machine/human evidence tied to artifact/config hashes | **UNVERIFIED** for production acceptance. This report records local checks and starting HEAD, not a hash-bound production soak. Historical runs are not evidence for the current RC. |

## Disposition and handoff

**BLOCKED**, not integration approval. Neither the historical schema failure nor
an unbanked vulture identity reproduced. No code, tests, inventory, ledger, or
grant changes are justified by these checks. Only this report changed; no new
tests means no inventory delta. No merge conflict or ref refresh was involved.

Next: designate the immutable promotion artifact and effective configuration,
resolve the shared-budget/receipt and reclaim-contract constraints, and provide
a production-artifact workload/telemetry runner covering the omitted surfaces.
Then run the representative at-least-four-hour soak with active physical work,
crash/drain/restart and stale-writer evidence, recording all artifact/config
hashes. Another run of the already-passing schema/vulture checks cannot satisfy
these acceptance criteria. Do not relabel host preflight as production proof.

Progress: checked 1 issue, done 0 acceptance-complete issues, skipped 0 issues,
errors 0 validation commands; next: RC prerequisites and production soak.
Local whitespace validation and commit complete the writer handoff.
