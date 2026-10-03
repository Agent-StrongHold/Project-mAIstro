# Issue #860 — round 18 validation checkpoint

**BLOCKED; not promotion evidence or integration approval.**

## Frozen scope

Only issue #860 and the explicitly assigned vulture per-identity gate, in
`/home/dev/Git/wt/auto-860`, starting at clean HEAD
`8612da416aeede680dfb78d7d47c73ff686bbe48`. No incoming diff to salvage.
The assigned develop base resolves; its three-dot diff is empty. No sync
conflict was observed. No remote actions are needed or authorized.

Read-only inspection scope: repository instructions; accepted runtime,
recurrence, rate-policy and evidence ADRs; `scripts/soak/run_soak.py`;
`docs/testing/soak/m3a-load-profile.md`, existing evidence and round 17 handoff;
`tests/test_soak_promotion_gates.py`; adjacent task, rate and learning-store tests;
production middleware and Compose wiring; `scripts/check-vulture-baseline.py`
and its ledger if the required scan reports an unbanked identity.
Planned edit scope: this checkpoint, plus only demonstrated gate repairs if any.

The job directory snapshot contains no `check-*.log` files. Prior result JSON
was read but is not fresh validation. `scripts/run_soak.py` was not found;
that guessed path is skipped in favor of the recorded `scripts/soak/run_soak.py`.

Assumption: this assignment does not designate an immutable promotion RC image
and configuration. Do not substitute a host-process preflight or unit tests for
four-hour production-topology evidence. The previous block is an acceptance
block, not a merge conflict. Current evidence already retracts the old shared
rate-limiter claim; verify behavior rather than rewriting historical artifacts.

## Architecture reconciliation

Read `AGENTS.md`, `CLAUDE.md`, accepted ADR-081426-1f7c (runtime),
ADR-082126-f69c (recurrence), ADR-085 (rate policy), and ADR-083026-a91e
(absent metrics), plus the profile, evidence, middleware wiring and adjacent
regressions. Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`.
A unique admitted Run is not proof of unique physical Attempt execution.
Principal-keyed rate policy does not imply shared state. Missing measurements
are not zero-valued success. No competing execution or authorization path was
introduced to make a soak pass.

## Fresh validation

All commands ran with 1800-second timeouts in the assigned worktree:

| Command | Result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1402 reviewed identities / 1402 findings; zero unclassified and never-allowlist findings. No ledger amendment warranted. |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-core/tests/persistence/test_pg_learnings.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py packages/maistro-server/tests/api/test_rate_limit.py -x -q -rs` | 102 passed, 5 skipped in 11.93 s. All skips require `MAISTRO_TEST_PG_DSN`; no live PostgreSQL validation claimed. |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS: 2624 files already formatted |
| `uv run python scripts/check-suite-inventory.py --suite tests/` | PASS: 4198 tests |

An inline `uv run python -` imported the current evaluator and asserted both
`sustain_duration` and `exact_rc_artifact` fail for each frozen historical pack:
`m3a-soak-evidence.json`, `m3a-repair-validation.json`, `m3a-round5-final.json`,
and `m3a-round6-shakedown.json`. Top-level durations were absent, absent,
90.17 s and 90.43 s respectively. It also asserted the current
`preflight_artifact_check()['ok'] is False`. This replays evidence rejection;
it is not a new soak or independent validation of historical measurements.

## Acceptance audit

| Criterion | Executed evidence / disposition |
| --- | --- |
| Representative RC profile | PARTIAL / UNVERIFIED: profile defines mix and thresholds but explicitly lacks concurrent users/Workspaces, fan-out, successful tools/models, Design/Canvas and sustained Goal/background activity. |
| Two supported application replicas | UNVERIFIED: inspected two-service production Compose declaration; ASGI middleware instances do not constitute deployed RC replicas. |
| Sustained saturation, reclaim, retry, leaks and shutdown | UNVERIFIED: all four historical packs fail duration; live sampler regression proves child measurement, not application health over a sustained window. |
| No duplicate physical work and Goal reconciliation | UNVERIFIED: task regression starts no runner; schedule probe races admission then cancels the queued Run. Neither supplies a physical-effect oracle. |
| Concurrent rate/security/degraded non-bypass | NOT MET for aggregate allowance: executed production-middleware regression observes `[200,200,429]` independently on each replica for the same credential or IP. `main.py:478` installs this middleware; `api/rate_limit.py:25-30` documents independent process-local state. RC security/degraded behavior remains UNVERIFIED. |
| Complete telemetry and explicit thresholds | PARTIAL / UNVERIFIED: profile thresholds and live child RSS/descriptor test exist; DB sampler is mocked in that test, five PG tests skipped, no sustained RC application-loop/worker census. |
| Kill/restart during active work with recovery/fencing | UNVERIFIED: no active-work restart executed; historical process exit and terminal Run counts do not prove Attempt effects were fenced. |
| >=4-hour exact RC/config soak | BLOCKED: no designated immutable RC/config; current harness explicitly rejects equivalence (`scripts/soak/run_soak.py:635`). Historical 90.43 s remains below 14400 s. |
| Findings classified to earliest invariant | PARTIAL / UNVERIFIED: existing F11/F12 classify evidence-validity failures to M3-A; no new load run or external filing performed. GitHub mutations prohibited. |
| Hash-tied human/machine evidence | PARTIAL / UNVERIFIED: historical packs are preserved and mechanically rejected; no qualifying promotion pack produced. |

## Handoff

The only changed file is this checkpoint. No source, runtime configuration,
ledger or tests changed; no test inventory delta is required. The previously
reported limiter prose contradiction is already corrected in the current
human-readable evidence, but the production acceptance mismatch is not.

Release owner must designate an immutable RC/configuration, resolve the
aggregate-rate acceptance mismatch through the owning work, complete production
workloads and physical-effect/telemetry oracles, then execute and publish at
least four hours on that exact artifact/topology. Any code/runtime-config
change requires a new soak. A green ledger cannot remove these blockers.

Progress: `{checked: 1, done: 0, skipped: 0, errors: 0, next: designated RC and
production-path sustained evidence}`. Focused validation completed; issue
acceptance remains blocked. This checkpoint is committed locally.
