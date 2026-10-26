# Issue #860 — bounded repair c9cda998

## Frozen scope

- Issue #860 only; assigned worktree `/home/dev/Git/wt/auto-860`, branch
  `auto-860`, starting HEAD `02fb276ce52b8f9bde0e19cdcd3c62063407cafa`,
  base `d99e598e1084a183d1280fbe9a2c4de8b50b7f2b`; clean on arrival.
- Inspect current soak runner/profile/tests, production learnings schema and its
  regression test, relevant ADRs/instructions and CI gate configuration.
- Run the requested exact vulture gate; edit its ledger only if actual findings
  require reviewed retained identities. No guessed debt, grants or gate changes.
- Candidate edits limited to those source/test files if reproduced defects
  warrant them, associated inventory note, and this report. No remote mutations.
- Snapshot evidence: supplied dispatch-context.json issue acceptance and prior
  result.json. No check-*.log files were present in this job directory. Supplied
  prior check-3.log reports schema fence test expected 21 statements but saw 24.
- Ambiguity: this is a writer repair assignment, not a verifier-only assignment.
  Treat prior BLOCKED claims as hypotheses; do not declare exact-RC promotion
  without executing its acceptance evidence. No assigned immutable RC identity
  is supplied by the lane brief.

## Results

- Exact requested vulture command: PASS, 1,326 findings and 1,326 reviewed
  identities; no unclassified or forbidden findings. No ledger change justified.
- `uv sync --locked --extra dev`: PASS.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`:
  **37 passed, 6 skipped**. Historical check-3 failure does not reproduce. Current
  expected DDL includes all three validation-audit columns; no test weakening or
  production schema change justified. Skips are not live PostgreSQL evidence.

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3,195 files.
- `uv run python scripts/check-merge-markers.py`: PASS.
- `uv run pytest tests/test_soak_promotion_gates.py
  tests/test_prod_stack_boot_contract.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  packages/maistro-server/tests/api/test_rate_limit.py -x -q`:
  **100 passed**. These include production-middleware independent-allowance
  regressions and CLI rejection of synthetic four-hour preflight evidence.

Existing work is preserved; no changes to execution authority. No demonstrated
CI failure remains in the reported checks. No source/test/ledger edit is
justified by these results.

## Acceptance review and architecture reconciliation

Read accepted ADRs 081426-1f7c, 081626-f383, 082526-b36a and 073126-c4e1.
Physical execution identity is Attempt, canonical persistence owns the lease
and fence, and expiry/renewal—not restart alone—establish reclaim authority.
Admission counts cannot substitute for physical-work or recovery evidence.
The immutable RC release contract does not authorize inventing a selected RC
from this repair worktree. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`.

A fresh `uv run python -` imported the current runner and evaluated
`docs/testing/soak/evidence/m3a-round30-shakedown.json`: **420.08 seconds**
versus **14,400 required**, with failed checks exactly `sustain_duration` and
`exact_rc_artifact`. Assertions confirming rejection passed. This is evaluation
of historical evidence, not a newly executed soak.

| Acceptance | Current evidence and disposition |
| --- | --- |
| Representative RC load profile | **UNVERIFIED complete.** `m3a-load-profile.md:145–164` identifies missing users/Workspaces, Graph fan-out, successful model/tool calls, Canvas and Goal workloads. Runner `1372–1395` uses one key and a limited mix. |
| Two application replicas | **UNVERIFIED deployed RC.** `deploy/docker-compose.prod.yml:26–77` declares two services; executed boot tests verify configuration, not deployed sustained load. |
| Sustained saturation, growth, reclaim, retry and leaks | **UNVERIFIED.** Current evaluator rejects historical duration; sampler tests prove measurement behavior, not long-running production behavior. |
| No duplicate physical work / Goal reconciliation | **UNVERIFIED.** `scripts/soak/run_soak.py:1044–1072` cancels the schedule admission probe without executing it. No active Attempt physical-work oracle or Goal workload was run. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **UNVERIFIED overall; independent allowances reproduced.** Executed `tests/test_soak_promotion_gates.py:439–493` observes `[200, 200, 429]` independently on each production limiter for the same identity. `rate_limit.py:32–37` documents this local scope. Local backpressure/auth tests are not cluster-budget proof. |
| Complete telemetry with explicit thresholds | **UNVERIFIED.** `run_soak.py:1410–1424` measures driver, not application, loop lag. Profile explicitly leaves saturation/reclaim/worker and long-window observations outstanding. |
| Active-work kill/restart drain/fencing/recovery | **UNVERIFIED.** `run_soak.py:1427–1489` checks process/HTTP recovery, not physical Attempt ownership. No new live kill/restart experiment was performed. |
| Long soak of exact promoted RC/configuration | **BLOCKED / UNVERIFIED.** `run_soak.py:730–741` deliberately rejects this host-process preflight as exact-RC evidence. Executed CLI tests confirm a synthetic four-hour preflight still fails. No selected immutable RC and full configuration were supplied. |
| Findings filed/reclassified before promotion | **UNVERIFIED completeness.** Existing reports do not establish that a complete representative audit was run. No remote mutations performed or permitted. |
| Machine/human evidence bound to exact hashes | **UNVERIFIED current RC.** Historical JSON and this check report are not a new exact-RC soak evidence pack. |

## Handoff

**BLOCKED**, not merge-ready. Changed only this report; no inventory delta is
needed because no tests were added or changed. No ledger amendment is warranted
by a clean exact scan. No failing production behavior was repaired this round;
passing focused CI checks do not resolve the missing promotion evidence.

Next: supply the selected immutable RC/configuration, complete the representative
production-path workload and Attempt-level recovery/telemetry oracle, resolve
replica-selection enforcement expectations without a competing authorization
path, then run the required long soak and publish fresh hash-bound evidence.
A longer invocation of the current preflight cannot meet that prerequisite.

All validation commands used 600–1,800-second timeouts. No full-tree pytest,
Docker load run, GitHub mutation, merge, reset or destructive cleanup was done.
This report is the local commit checkpoint for the blocked item.

Progress: {checked: 1, done: 0, skipped: 0, errors: 0,
next: selected-RC prerequisites and missing production acceptance evidence}.
