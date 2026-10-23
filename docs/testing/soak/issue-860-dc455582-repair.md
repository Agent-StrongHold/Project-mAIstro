# Issue #860 repair — dc455582

## Frozen scope

- Only issue #860, branch `auto-860`, starting head
  `5562dc5681ef4fc0fe5b4f19b48972e811069058`, base
  `e1b13dcd15dedd637404c38dfe1900921aba2b8c`.
- Inspect existing soak runner/profile/evidence and adjacent tests, the reported
  `test_pg_learnings.py` failure, and exact vulture findings. Modify only a
  reproduced defect, reviewed retained vulture identities if any, and this report
  (plus inventory note if tests change). No other issues or PRs processed.
- Worktree initially clean; no salvage required. Supplied job directory contains
  no `check-*.log`; inspected the explicitly supplied prior `98a11313.../check-3.log`.
  It reports 24 actual DDL statements versus 21 expected. Current behavior will be
  rerun rather than assuming that old failure remains.
- Ambiguity: assignment is a writer repair, not verifier-only. Proceed with focused
  validation and a local commit; no remote mutations or deployment claims.

## Progress

- `uv sync --locked --extra dev`: PASS, 206 installed packages checked.
- Exact requested vulture command: PASS, 1332 reviewed identities / 1332
  findings, zero unclassified/forbidden. No ledger amendment is justified.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py
  -x -q`: 37 passed, 6 skipped. Supplied schema failure is not reproducible.
- `uv run pytest tests/test_soak_promotion_gates.py
  tests/test_prod_stack_boot_contract.py tests/test_gitleaksignore_contract.py
  packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py
  packages/maistro-server/tests/api/test_rate_limit.py -x -q`: 104 passed.
- `uv run ruff check .`: PASS. `uv run ruff format --check .`: PASS (3105 files).
- `git diff --check`: PASS at checkpoint.

These are newly executed checks, not adoption of prior verification claims.
No production code or tests need changing based on the supplied CI findings.
Unit tests alone cannot prove the RC soak.

## Architecture and reachable behavior

Read repository instructions, the documentation authority map, and accepted
ADRs 081226-69ee (Graph execution), 081626-f383 (Attempt fencing), 082526-b36a
(lease renewal/reclaim), 082826-08f0 (recovery dispositions), and 085 (principal
rate limits). Preserve `Goal -> Graph -> Run -> NodeRun -> Attempt`. The later
recovery table governs the older fencing ADR's deferred takeover boundary:
restart never authorizes stealing a live lease. No competing execution,
authorization, event, or Goal authority is introduced.

- `packages/maistro-core/src/maistro/container.py:3090` calls the real learning
  store's schema upgrade. Its three Gauntlet audit columns appear in production
  `_EPISTEMIC_COLUMNS` and in the independent ordered test expectations at
  `packages/maistro-core/tests/persistence/test_pg_learnings.py:175-177`.
  The reported 21-versus-24 mismatch is already repaired at the starting head.
- `packages/maistro-server/src/maistro_server/main.py:648` installs the real
  `RateLimitMiddleware`. Each instance constructs `InMemoryRateLimiter` at
  `api/rate_limit.py:74`. The executed test at
  `tests/test_soak_promotion_gates.py:439-488` shows identical credentials/IP
  exhaust one instance yet receive two more successful requests on the other.
  Principal-keyed local enforcement is not a shared principal allowance.
  ADR-085 does not choose a distributed storage implementation; this repair
  does not invent one or waive #860's replica-selection criterion.
- `deploy/docker-compose.prod.yml:26-76` defines two server replicas, but the
  file explicitly identifies itself as a reference deployment, not an immutable
  selected RC. `scripts/soak/run_soak.py:730-741` explicitly marks the existing
  runner as host-process preflight, never the exact promoted Compose artifact.

## Additional executed validation

All validation used `uv run`; long-running tool calls used 1200-second timeouts.

- `uv run python scripts/check-suite-inventory.py`: PASS, 17 suites, 28182
  unique identities, no duplicate evidence.
- `uv run python scripts/check-backlog-consistency.py`: PASS, 168 items.
- `uv run python -` imported the current soak runner with `importlib`, loaded
  `docs/testing/soak/evidence/m3a-round6-shakedown.json`, and called
  `failed_promotion_checks`. Asserted both `sustain_duration` and
  `exact_rc_artifact` fail, and `preflight_artifact_check()['ok'] is False`.
  Observed duration: 90.43 seconds; required: 14400 seconds. This evaluates
  historical evidence; it is **not** a new live soak.

## Acceptance matrix

| Criterion | Current evidence / disposition |
| --- | --- |
| Representative RC profile | UNVERIFIED. Profile documents traffic but acknowledges missing multi-user/Workspace, fan-out, successful model/tool, Design/Canvas and background/Goal workloads at `m3a-load-profile.md:153-172`. |
| At least two production application replicas | UNVERIFIED live. Compose defines two; executed ASGI instances are not production replicas. |
| Sustained saturation, queues, leases, retries, memory/descriptor/process leaks | UNVERIFIED. No sustained production workload executed; sampled historical run is only 90.43 seconds. |
| No duplicate physical work; schedule/task/Run/Attempt and Goal reconciliation | UNVERIFIED. Admission probes do not establish physical-work fencing. Profile lines 195-204 acknowledge cancellation of the scheduled probe before execution. |
| Security/degraded/rate enforcement, no replica-selection bypass | Shared principal allowance is falsified by executed real middleware test at `test_soak_promotion_gates.py:439-488`; sustained security/degraded behavior remains UNVERIFIED. |
| Complete PostgreSQL/application-loop/process/queue/error telemetry and thresholds | UNVERIFIED. Sampler tests pass, but driver-loop lag is not application-loop lag and no current production series was collected. |
| Kill/restart during active work, graceful drain/fencing/recovery | UNVERIFIED. No live active-Attempt interruption experiment executed. |
| Long-running exact RC/configuration soak | NOT MET by evaluated evidence: duration and artifact checks fail. No designated immutable RC/configuration supplied for a promotion run. |
| Findings filed/reclassified before promotion | UNVERIFIED. Local findings are recorded here; backlog gate cannot establish completeness. GitHub mutation prohibited and not performed. |
| Machine/human evidence tied to exact artifact/config hashes | UNVERIFIED for production RC. Historical files and this report do not certify an unselected artifact. |

## Handoff

**BLOCKED** on production acceptance, not on either supplied CI repair target.
Only this report changed. No tests added, so no inventory delta is required.
No ledger/grant edit is supported by the scan. No production deployment started,
no remote mutations, no merge conflict encountered, and existing work preserved.

Next: supply the immutable promotion RC and configuration, complete the
representative workload and physical-work/recovery oracles, resolve aggregate
rate-limit semantics, then run the required >=4-hour production soak and publish
hash-bound evidence. Repeating the stale schema failure or a clean vulture scan
cannot resolve those prerequisites. Do not treat this local commit as integration
approval or issue closure.

Progress: {checked: 1, done: 0, skipped: 0, errors: 0, next: production RC
acceptance prerequisites}. Focused validation complete; issue acceptance blocked.
