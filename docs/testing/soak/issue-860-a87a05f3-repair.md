# Issue #860 — merge salvage and CI repair a87a05f3

## Frozen scope and preserved state

Assigned issue #860 only, worktree `/home/dev/Git/wt/auto-860`, starting HEAD
`2619c041738d929ac7741925b919551959462e75`. Incoming MERGE_HEAD already names the
assigned develop base `34795962548a33f6b6f7e1234dcea201a9df96ef`; do not refresh it
or expand this frozen assignment to a newer develop. The incoming staged changes
are that unfinished merge, not permission to implement other issues.

Before editing, preserved unstaged/conflict and staged state in
`/home/dev/Git/wt/incoming-860.patch` and `incoming-860-index.patch`.
The only conflict was `scripts/ci_merge_group_scope.py`: equivalent membership
versus equality expressions for the two wheel-import job scripts. Resolved using
the incoming expression, preserving both verifier triggers and all package
triggers. No gate was weakened. Existing tests cover both scripts independently
and PR/merge-group scope parity. No new tests or inventory delta in this round.

Read repository instructions and accepted ADR-081226-a66b, ADR-081626-f383,
ADR-082526-b36a and ADR-085, plus proposed ADR-081. Preserve the single
`Goal -> Graph -> Run -> NodeRun -> Attempt` authority. Admission uniqueness is
not physical-work uniqueness; a proposed deployment ADR does not waive the
production soak requirement. No execution or authorization path was changed.

## Evidence checkpoint

Job logs: `/home/dev/maistro/jobs/a87a05f3214a4bc4980c4dae58b30595/worker-*.log`.
No driver `check-*.log` files were present in this job at intake. Read the supplied
historical `98a11313167b41a98a420abfda80c292/check-3.log` and prior result; neither
is treated as current verification.

- Exact requested `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1,326 findings,
  zero unclassified/never-allowlist. No scanner-evidenced ledger repair needed.
  Incoming ledger is identical to the assigned develop base; preserved unchanged.
- `uv run pytest tests/test_ci_merge_group_scope.py
  tests/test_ci_merge_group_outputs.py tests/test_ci_specialized_scope_wiring.py
  tests/test_pr_scope_policy_parity.py tests/test_check_integration_scope.py -x -q`:
  **77 passed** (`worker-scope.log`).
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  **37 passed, 6 skipped** (`worker-schema.log`). Historical 24-versus-21 DDL
  mismatch is not reproduced: the independent expected list already includes
  the three Gauntlet audit columns. Skipped tests are not live PostgreSQL proof.

- `uv run pytest tests/test_soak_promotion_gates.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  **66 passed** (`worker-soak.log`). This exercises the real HTTP backpressure
  route/canonical admission seam and production rate middleware, not a live
  multi-replica deployment or physical executor.
- `uv run ruff check .`: PASS; `uv run ruff format --check .`: PASS (3,170 files).
- `uv run python scripts/check-deployment-claims.py`: PASS (static claims only).
- `uv run python scripts/check-backlog-consistency.py`: PASS (168 items).
- Executed an `uv run python` importlib probe of current `run_soak.py` against
  `evidence/m3a-round30-shakedown.json`: current `failed_promotion_checks`
  returns exactly `sustain_duration` and `exact_rc_artifact`; current
  `preflight_artifact_check()` returns `ok: false` (`worker-artifact.log`).

Commands used 1,000–1,200 second timeouts. No new production soak was run: the
assigned snapshot identifies no immutable promotion image/configuration, and
lengthening the explicitly ineligible host runner cannot establish acceptance.

## Acceptance disposition: BLOCKED

| Issue criterion | Executed evidence or explicit limit |
| --- | --- |
| Representative RC workload | **UNVERIFIED**. `m3a-load-profile.md:147` lists missing concurrent users/Workspaces, fan-out, successful model/tool calls, Design/Canvas and Goal/background workers. Selected-RC applicability is not established. |
| At least two production application replicas | **UNVERIFIED** for this candidate. `deploy/docker-compose.prod.yml:26,77` defines two services; tests do not deploy them. |
| Sustained saturation, queue growth, expiry/reclaim, retry, leaks and restart | **UNVERIFIED**. No long production run; fresh evaluation rejects historical duration evidence. |
| No duplicate physical work across replicas | **UNVERIFIED**. Backpressure tests intentionally start no runner; the profile's schedule probe cancels its queued Run without physical execution. Admission uniqueness is insufficient. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **UNVERIFIED** at deployment level; independently reproduced extra allowances. `tests/test_soak_promotion_gates.py:439` gives the same identity `[200,200,429]` on each middleware instance. `main.py:648` installs this middleware; `api/rate_limit.py:93` creates its process-local limiter. Existing per-replica semantics are not cluster-wide proof. |
| Complete production telemetry with thresholds | **UNVERIFIED**. The profile acknowledges driver-loop rather than application-loop latency, incomplete worker coverage, and missing long-window saturation/reclaim/leak observations. |
| Kill/restart during active work with fencing/recovery | **UNVERIFIED**. No exact-RC physical-work restart executed. Rejoin/terminal counts cannot prove absence of loss or duplication. |
| Long soak of exact RC artifact/configuration | **UNVERIFIED**. Current runner fails its artifact check; historical evidence fails artifact and duration gates under freshly executed logic. |
| Findings reclassified to earliest broken milestone invariant | **UNVERIFIED** completeness. This report records blockers; no GitHub mutations permitted or performed. |
| Machine/human soak evidence tied to exact hashes | **UNVERIFIED** for this candidate. Local validation logs and this report are not production soak evidence. |

## Changes, residual risk and next action

This round resolves `scripts/ci_merge_group_scope.py` and adds this report. The
other staged files belong to the incoming develop merge and are preserved in the
merge commit, including its ledger changes; no additional ledger/grant changes
were authored. The resolved script equals the assigned develop version, retaining
both sides' intended behavior. Focused tests do not validate every unrelated
change imported by that merge.

CI repair is complete; issue acceptance is not. Supply immutable promotion
artifact/configuration identity and a production-topology runner that covers the
missing workload, physical-effect, telemetry and recovery probes. Resolve the
replica-selection budget contract through the existing authorization path. Then
execute the profile's minimum four-hour exact-RC soak and publish hash-bound
results. Do not repeat passing CI repairs or rename emulator output as promotion
proof. No scheduler, Goal store, event authority or authorization path was added.

Final whitespace check: `git diff --check` passes. `git diff --cached --check`
flags `docs/issue-42-ci-repair.md:144: new blank line at EOF` in the inherited
develop merge. Preserve that unrelated file rather than silently expand #860's
repair scope. This is not a Python validation failure.

Checkpoint: checked 1 issue; done 0; skipped 0; validation errors 1 (inherited
whitespace); blocked 1.
Local commit is a salvage/repair handoff, never integration approval.
