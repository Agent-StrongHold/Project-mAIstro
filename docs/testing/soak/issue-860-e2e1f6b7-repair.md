# Issue #860 repair — e2e1f6b7

## Frozen scope

Only issue #860 in `auto-860`, starting at
`6850fd33fef0e73322c11ac71b380857c6e032de`, supplied base
`3c761d14db944a727fa0744444bc67cfe36d49f7`.
Starting worktree was clean. No check-*.log files were present in this job's
initial directory listing. The supplied prior check-3.log reports the learnings
schema-fence test expecting 21 statements but observing 24.

Files eligible for repair: `packages/maistro-core/src/maistro/persistence/pg_learnings.py`,
its adjacent `tests/persistence/test_pg_learnings.py`, `scripts/soak/run_soak.py`,
`tests/test_soak_promotion_gates.py`, and `quality/vulture-baseline.json` only for
actual reviewed findings from the explicitly requested scan. Documentation is
limited to this report and an inventory note if tests change. Existing branch
work is preserved. No unrelated historical branch changes will be repaired.

Assumption: this is a writer CI-repair round, not authorization to designate an
RC or substitute host preflight evidence for deployed release acceptance.

## Results

Fresh validation: the exact requested vulture command passed (1323 reviewed
identities / 1323 findings, zero unclassified; provenance base 4aa68edc0b6b).
No ledger amendment is warranted. The reported schema failure does not reproduce:
`uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q`
passed with 37 passed / 6 skipped. Logs: `/tmp/860-e2e-vulture.log` and
`/tmp/860-e2e-pg.log`. Database skips are not live multi-replica evidence.

The issue body was extracted from the frozen dispatch JSON. All ten acceptance
criteria require evaluation; passing the CI repair checks alone cannot satisfy
the exact-RC soak requirement. The supplied previous handoff and current profile
both acknowledge RC workload/telemetry gaps, checked against the gate and adjacent
tests. `scripts/soak/run_soak.py:730` returns `ok: False` for exact RC identity;
no elapsed duration can change its host-preflight topology.

Additional fresh commands (all exit 0, long timeouts):

- `uv run ruff check .`: all checks passed (`/tmp/860-e2e-ruff.log`).
- `uv run ruff format --check .`: 3270 files already formatted
  (`/tmp/860-e2e-format.log`).
- `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  66 passed (`/tmp/860-e2e-soak-tests.log`).
- `uv run python scripts/check-suite-inventory.py`: 17 suites, 31128 unique
  identities, zero duplicated evidence (`/tmp/860-e2e-inventory.log`).

No test changes or count delta; no inventory note needed. No scanner finding or
reproducible CI failure justifies changing production code or the ledger.

## Architecture and acceptance

Read repository instructions, docs/README.md, accepted ADR-081226-69ee,
ADR-081626-f383, ADR-082526-b36a and ADR-085. The later renewal/reclaim ADR
extends the original fencing boundary; reclaim is not treated as deferred.
ADR-081 was also read: it is **Proposed**, not an accepted deployment waiver.
Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`; no new scheduler,
authorization path or execution authority is introduced.

Production `maistro_server/main.py:648` installs `RateLimitMiddleware`;
`api/rate_limit.py:93` creates its instance-local limiter. Executed
`tests/test_soak_promotion_gates.py:439` exercises that middleware for the same
identity on two instances: each accepts two requests then returns 429. This is
real local enforcement, not cluster-wide budget proof. ADR-085's per-principal
keying does not justify claiming cross-replica enforcement. Resolving this
acceptance gap requires a governed deployment/rate-limit disposition, not a
speculative CI patch.

| Acceptance criterion | Current executed evidence / disposition |
| --- | --- |
| Representative RC users/Workspaces, request mix, fan-out, schedules, model/tools, Design/Canvas and workers | UNVERIFIED. `m3a-load-profile.md:155` acknowledges omitted workloads. No immutable RC/configuration is designated in the assignment. |
| At least two deployed application replicas | UNVERIFIED. Two middleware test instances are not deployed exact-RC replicas. |
| Sustained pool/queue/reclaim/retry/memory/descriptor/process observations | UNVERIFIED. Real child-process sampler regression passes, but no sustained deployed load was executed. |
| No duplicate physical work across schedule/task/Run/Attempt/Goal paths | UNVERIFIED. Admission-probe regression checks canonical receipt identities, not physical-work uniqueness. |
| Rate/security/degraded behavior cannot be bypassed by replica selection | UNVERIFIED at deployment grade; independent allowances reproduced as above. Backpressure tests pass but do not establish a shared budget. |
| Complete telemetry and explicit pass/fail thresholds | UNVERIFIED. Thresholds exist in the profile, but `run_soak.py:1410` measures driver-loop rather than application-loop lag; required production saturation/reclaim observations are absent. |
| Active-work replica kill/restart, drain, fencing and recovery | UNVERIFIED. Boot cleanup tests pass; no active RC replica was killed/restarted this round. |
| Long soak of exact RC artifact/configuration | BLOCKED / UNVERIFIED. `run_soak.py:1552` wires the always-failing host-preflight artifact check into emitted evidence. Executed CLI regression rejects synthetic four-hour preflight evidence; it did not run for four hours. |
| Findings filed/reclassified before promotion | Local disposition: replica allowance is rate/security correctness, not throughput. External filing/reclassification UNVERIFIED; GitHub mutations prohibited. |
| Machine/human evidence bound to exact image/package/commit/config hashes | UNVERIFIED for RC. This report binds source validation to starting HEAD, not a designated image/configuration or completed soak. |

## Handoff

Only this report changed in this round. Existing historical branch changes were
preserved, not independently certified by focused checks. No merge conflict was
present; no fetch/merge was necessary. No source, tests, inventory, ledger or
grants were changed. `git diff --check` is run before the local commit.

Verdict: **BLOCKED**. Required next input is a designated immutable RC and runtime
configuration, with applicable workload scope. Then an exact-topology runner
must capture full telemetry and physical-work witnesses through a minimum
four-hour soak including active-work recovery; invariant failures must be
resolved/dispositioned before promotion. Another clean CI scan or host preflight
cannot supply that missing evidence. This commit is a handoff, not approval.

Progress: checked 1, done 0 (acceptance incomplete), skipped 0, validation errors 0.

