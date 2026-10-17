# Issue #860 — bounded repair validation (895411b5)

## Frozen scope

One item: issue #860, branch `auto-860`, starting head
`103a652de28d0e59bd4e2239b1db21547f3a2597`, supplied base
`376b0e1301da7257cb098bde9b43ce9d99a642c4`.
Starting worktree clean; no incoming diff to salvage. No GitHub mutations.
Use only the supplied dispatch snapshot, not live issue/PR enumeration.

Repair candidates are limited to the reported schema-fence regression in
`packages/maistro-core/tests/persistence/test_pg_learnings.py`, its production
implementation `packages/maistro-core/src/maistro/persistence/pg_learnings.py`,
and reviewed findings from the required exact vulture scan in
`quality/vulture-baseline.json`. Acceptance validation reads the existing
`scripts/soak/run_soak.py`, `tests/test_soak_promotion_gates.py`, load profile,
and retained evidence. This report and an inventory note (only if needed) are
the documentation scope. Do not alter unrelated inherited branch changes.

## Initial evidence and assumptions

No `check-*.log` files exist in the supplied current job directory. The explicitly
supplied prior `98a113.../check-3.log` reports 24 schema statements versus 21
expected. This is historical evidence, pending fresh reproduction.
The prior result is BLOCKED on missing exact-RC soak and production coverage;
its claims are not assumed verified. No exact RC identity/configuration was
provided in this assignment. A host preflight must not stand in for deployed RC
promotion evidence. No merge conflict is present, so the conditional develop
sync instruction does not apply.

## Results

- `uv sync --locked --extra dev`: PASS.
- Required exact vulture scan: PASS, 1,326 reviewed identities / 1,326 findings,
  zero unclassified or never-allowlist findings. No ledger amendment justified.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  -x -q`: 37 passed, 6 skipped (1.90 s). The historical failure does not
  reproduce: the independent expected DDL list already includes all three
  validation audit columns. No test or production repair justified.
- Read accepted execution ADRs 081426-1f7c and 081626-f383. Physical work is
  identified by Attempt, not admission. Lease fencing does not itself promise
  expiry-based takeover. Acceptance cannot be met by inventing a scheduler or
  treating admitted Runs as executed Attempts.

- `uv run pytest tests/test_soak_promotion_gates.py
  tests/test_prod_stack_boot_contract.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  packages/maistro-server/tests/api/test_rate_limit.py -x -q`: 100 passed
  (2.91 s), including real production rate middleware instances and the real
  child-process resource sampler. These are focused regressions, not a deployed
  multi-replica soak.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS (3,195 files).
- `uv run python scripts/check-merge-markers.py`: PASS.
- All validation batches used 1,200-second timeouts.

- `uv run python -` imported the actual soak evaluator and checked retained
  `evidence/m3a-round30-shakedown.json`: 420.08 seconds versus the 14,400-second
  minimum; failed checks exactly `sustain_duration` and `exact_rc_artifact`.
  Assertions verified both failures and that the current driver's artifact
  check remains false. This is negative validation, not a new soak.
- Read accepted ADR-082526-b36a: it extends the earlier fencing contract with
  opt-in TTL, renewal and reclaim through canonical Attempt execution/store
  seams. These existing mechanisms need an observed workload, not replacement.
  Read ADR-073126-c4e1: RC selection and immutable artifacts follow the existing
  release process. An arbitrary local build is not automatically the RC.
- The supplied snapshot's latest issue comments and PR #1672 body do not
  identify a selected RC or remove the previously reported acceptance blocker.
  No remote query or ref changes were performed.

## Acceptance audit

| Criterion | Fresh evidence and disposition |
| --- | --- |
| Representative release-candidate profile | **UNVERIFIED complete.** Read `m3a-load-profile.md:145–164` and driver `scripts/soak/run_soak.py:1372–1395`: one credential, narrow request mix, missing representative users/Workspaces, fan-out, successful model/tool calls, Canvas and Goal/background workloads. |
| At least two deployed application replicas | **UNVERIFIED for the RC.** `deploy/docker-compose.prod.yml:26–77` defines two services and boot-contract tests passed; no deployed exact-RC test executed. |
| Sustained saturation, queue growth, reclaim, retries and leaks | **UNVERIFIED.** Evaluator rejects the checked 420.08-second artifact. The real process-group sampler test passed, but does not establish sustained application behavior. |
| No duplicate physical work, including Goal reconciliation | **UNVERIFIED.** `scripts/soak/run_soak.py:1044–1072` cancels the admission probe's unexecuted Run. Admission deduplication is not an Attempt physical-work oracle. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | **UNVERIFIED overall; independent allowances reproduced.** Executed `tests/test_soak_promotion_gates.py:439–493`: same credential/IP receives `[200, 200, 429]` on each production middleware instance. `packages/maistro-server/src/maistro_server/api/rate_limit.py:32–37` explicitly defines process-local scope. Local enforcement/backpressure tests pass, but cannot certify a shared allowance. |
| Complete telemetry and explicit thresholds | **UNVERIFIED.** Driver `scripts/soak/run_soak.py:1410–1424` observes its own loop lag, not application loop lag. Profile explicitly leaves worker counts, saturation and long-window observations incomplete. |
| Kill/restart during active work proves drain/fencing/recovery | **UNVERIFIED.** `scripts/soak/run_soak.py:1436–1489` measures exit/rejoin and HTTP counters, not an observed active-Attempt physical-work oracle. No new kill/restart experiment ran. |
| Long exact-RC/configuration soak | **BLOCKED / UNVERIFIED.** `scripts/soak/run_soak.py:730–741` fails host preflight artifact identity regardless of duration. Fresh evaluation fails duration and artifact gates; no selected immutable RC/configuration supplied. |
| Findings filed/reclassified to earliest broken invariant | **UNVERIFIED completeness.** Historical classifications remain; no complete new load run or classification audit. GitHub mutations prohibited. |
| Machine/human evidence bound to exact image/package/commit/configuration | **UNVERIFIED for current RC.** Retained historical evidence and this validation report do not constitute an exact-RC evidence pack. |

## Handoff

**BLOCKED, not merge-ready.** No production, test, gate or ledger change is
justified by the supplied CI failure or fresh scan. Only this report changes;
no added tests, therefore no inventory delta. Existing branch changes remain
untouched. Six PostgreSQL-dependent tests were skipped; no claim of database
concurrency proof is made. Full package suites and a production soak were not
run; the focused commands above define the validation boundary.

Next: the release owner must identify the immutable RC image/package/config
through the canonical release process. Complete representative workload and
application telemetry/active-Attempt observation, reconcile the replica-budget
acceptance mismatch, then run at least four hours against that exact artifact.
Do not retry this same CI-repair loop without new failure evidence or those
prerequisites: passing static/unit checks cannot remove the production blocker.

Progress: {checked: 1, done: 0, skipped: 0, errors: 0,
next: selected RC and missing production acceptance evidence}.
The local documentation commit records diagnosis only, not integration approval.
