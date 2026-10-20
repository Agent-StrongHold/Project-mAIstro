# Issue #860 — fresh validation at `0792d109ec8e`

This is a writer-side evidence checkpoint for the frozen issue #860 scope, not
promotion approval. Starting HEAD matched the dispatch exactly and the worktree
was clean. The assigned job directory contained no `check-*.log` files, so no
driver checks were assumed to have run. The captured issue body requires a
representative multi-replica soak and exact-RC evidence; it does not authorize
weakening gates or treating emulator/unit evidence as production proof.

## Architecture and relevant evidence

Read repository `AGENTS.md`, issue acceptance in the supplied
`dispatch-context.json`, ADR-081 (Deployment Topology, Proposed), accepted
ADR-085 (Cost, Quota, and Rate Limiting), and accepted ADR-081226-a66b (Run,
NodeRun and Attempt Lifecycle). The execution authority remains the canonical
`Goal -> Graph -> Run -> NodeRun -> Attempt`; no scheduler, store, authorization
path, gate or runtime behavior was added. ADR-085 makes rate limiting
per-principal, but neither ADR changes the issue's stronger replica-selection
acceptance.

The load profile (`docs/testing/soak/m3a-load-profile.md`) expressly describes
the harness as a host-process preflight and says it cannot sign an exact
production Compose soak. It also identifies absent multi-user/Workspace,
Graph fan-out, successful tool/model, Design/Canvas and Goal/background
reconciliation traffic; driver-loop lag is not application-loop telemetry.
The schedule probe races admission, then terminalizes/cancels the queued Run
without executing physical work. These limits are explicit, not inferred from
missing log output.

## Fresh checks

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`: **PASS**, 1,326 reviewed identities / 1,326 findings, no unclassified findings. No vulture ledger amendment is supported or needed.
- `uv run pytest tests/test_soak_promotion_gates.py tests/test_prod_stack_boot_contract.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`: **PASS**, 93 passed.
- `uv run python scripts/check-reachability.py` and `uv run python scripts/check-ratchet-provenance.py`: **FAIL**. The new unreachable module is `maistro.runs.admission_identity`; its own module docstring says it is an inactive contract leaf with no production imports. The provenance wrapper reports the reachability failure. No reachability grant/baseline edit is in scope or permitted, and wiring an intentionally inactive API into production merely to silence the scanner would be an unjustified architecture change. This remains an unresolved branch gate.
- Independently imported `scripts/soak/run_soak.py` and evaluated `docs/testing/soak/evidence/m3a-round109-shakedown.json`: recorded head `5a59c724a20ef1241d57c048df90758f2c2e1e25`, duration `420.05` seconds; `failed_promotion_checks` returns `['sustain_duration', 'exact_rc_artifact']`. The profile requires at least 14,400 seconds, and the evaluated evidence is not the assigned head or an exact production artifact.

The supplied prior result's findings were rechecked where possible; they remain
consistent with the current source/profile. The driver report claimed 163
passes, but its referenced check logs were not in this job directory and are
not treated as this round's executions.

## Acceptance disposition

| Criterion | Evidence / status |
|---|---|
| Representative users/Workspaces, request mix, fan-out, schedules, queue, tools/models, Design/Canvas and workers | **UNVERIFIED / incomplete profile**; remaining gaps are stated in `docs/testing/soak/m3a-load-profile.md`. |
| Two application replicas in supported production topology | **UNVERIFIED**; middleware/component tests do not establish deployed production replicas. |
| Long sustained saturation, reclaim/retry/backoff, leak, shutdown/restart observations | **UNVERIFIED**; historical 420.05-second host preflight is below the 14,400-second minimum and not exact-RC. |
| Exactly-once schedule/task/Run/Attempt admission and physical work; Goal reconciliation | **UNVERIFIED**; schedule race establishes admission only and cancels its queued probe Run without executing it. No physical Attempt recovery soak was executed. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **NOT PROVEN**; `tests/test_soak_promotion_gates.py::test_replica_selection_has_an_independent_production_allowance` is among the 93 passing tests and explicitly observes independent `[200, 200, 429]` limits on two middleware instances for the same identity. Deployed behavior remains unverified. |
| PG usage/latency/locks, application-loop latency, worker/process counts, RSS, FDs, queue/error/timeout telemetry and thresholds | **UNVERIFIED at promotion grade**; no current exact-RC telemetry run. |
| Kill/restart during active work with drain/fencing/recovery and no loss/duplication | **UNVERIFIED**; no production active-work recovery run executed. |
| Long soak of exact RC/config; repeat after runtime change | **UNMET**; evaluator rejects historical evidence for duration and artifact identity. No RC image/config was supplied. |
| Findings reclassified to earliest broken invariant | **UNVERIFIED**; no GitHub issue mutations are allowed/performed. |
| Human- and machine-readable evidence tied to exact artifact/config hashes | **UNMET for promotion**; existing JSON identifies an older host preflight, not an RC artifact. |

No tests were added, so no suite-inventory delta is required. No source,
quality ledger, authorization, or soak evidence was modified. This item cannot
be made merge-ready in this lane: missing immutable RC designation and a
four-hour production execution are external prerequisites; the reachability
ratchet also requires a separately authorized disposition or an independently
justified production call path. Progress: `{checked: 1, done: 0, skipped: 0,
errors: 0, next: exact-RC production soak after RC designation; resolve
reachability disposition through its owning scope}`.
