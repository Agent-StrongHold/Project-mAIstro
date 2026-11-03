# Issue #860 — bounded repair b80c3041

## Frozen scope

- Issue: #860 only; no PR processing or remote mutations.
- Starting HEAD: `4dcb879bb0248fca3ecec70a1721a76076089d34` (clean).
- Supplied develop base: `0b336e3000b91bd3f404295c9849c3d880b8612b`.
- Inputs: supplied dispatch-context.json and prior dc1afc19 result.
- Check logs: none present in the supplied job directory at start.
- Planned write surfaces: this report; `quality/vulture-baseline.json` only if
  the prescribed scan demonstrates reviewed retained debt; an inventory note
  only if the reported suite discrepancy is reproduced. Production changes
  require concrete evidence and inspection before extending this list.
- Validation/read surfaces: repository instructions, relevant ADRs, soak
  profile/evidence, soak promotion tests/scripts, server rate limiter and its
  tests, vulture and inventory CI scripts/workflows.

## Assumptions

This is a writer/CI-repair round. The ledger exception permits reviewed
vulture identity changes, not weakening gates or creating grants. Historical
shakedowns are not a soak of this HEAD. Missing exact RC/configuration and
production observations cannot be replaced by passing unit tests.

## Progress

- Initial snapshot complete; no incoming edits to salvage.
- Prescribed vulture scan PASS: 1322 reviewed identities / 1322 findings,
  zero unclassified and never-allowlist. No ledger change is justified.
- CI workflow confirms the requested vulture arguments. Prior report shows
  missing RC acceptance, not a develop merge conflict; no merge is needed.
- Profile explicitly labels the host-process runner as non-promoting and
  documents unmeasured physical-work and representative-workload surfaces.
  Repeating that runner for four hours would not resolve exact-RC acceptance.
- `uv run ruff check .`: PASS. `uv run ruff format --check .`: PASS
  (3306 files).
- `uv run python scripts/check-suite-inventory.py`: PASS, all 17 suites,
  31,489 unique identities; root `tests/` = 5354. Reported mismatch is not
  reproducible, so no inventory adjustment is warranted.
- Production limiter inspection confirms independent per-process budgets;
  existing regression exercises both identity classes using real middleware,
  not a stubbed limiter.
- `uv run pytest tests/test_soak_promotion_gates.py -x -q`: PASS (84 tests,
  1.31 s), including independent replica allowance for both identity classes.
- `uv run pytest packages/maistro-server/tests -x -q`: PASS (566 passed,
  8 skipped, 31.49 s). 23 warnings include 22 HTTP status deprecations and
  one aiosqlite worker-thread `RuntimeError: Event loop is closed` warning
  attributed to `test_cancel_still_works_and_takes_the_run_with_it`. This is
  not a clean leak/recovery proof; no unrelated repair attempted.

## ADR reconciliation

Read accepted ADR-085, ADR-081626-f383, ADR-082426-82c7 and
ADR-082526-b36a. Occurrence uniqueness belongs on canonical Runs; execution
fencing belongs on canonical Attempts. Principal identity must use the
existing canonical authentication resolver. No alternate authority introduced.

**Correction to the prior handoff:** ADR-081626-f383's original boundary
left reclaim for later, but accepted ADR-082526-b36a subsequently defines
TTL/renewal/reclamation through `AttemptExecutionService` and canonical
store/lifecycle, with `Container.recover_abandoned_attempts` wiring. Missing
soak observation is not missing architectural authority. A production experiment
should exercise this existing mechanism, not invent a new sweeper or defer
reclaim as undefined. Passing admission probes still cannot establish physical
work fencing or reclaim. ADR-085 does not waive replica-selection acceptance.

## Executed acceptance checks

- Imported current `scripts/soak/run_soak.py` with `uv run python`, evaluated
  `docs/testing/soak/evidence/m3a-round30-shakedown.json`, and asserted the
  failures equal `['sustain_duration', 'exact_rc_artifact']`: PASS.
  Observed 420.08 s against minimum 14,400 s, historical commit
  `c4f45b309fd622f2e8a4b315dad35e721d81aad3`. Asserted the current runner's
  `preflight_artifact_check()['ok'] is False`: PASS.
- Confirmed production reachability: `maistro_server/main.py:648` installs
  the tested limiter. `rate_limit.py:32-37` explicitly documents N-times
  aggregate allowance; `test_soak_promotion_gates.py:477-526` freshly
  reproduces `[200, 200, 429]` independently on both replicas for one identity.
- Confirmed existing reclaim implementation:
  `maistro/container.py:1214,1260` delegates to canonical Run-store reclaim.
  Inspection is not a live multi-replica reclamation experiment.
- `deploy/docker-compose.prod.yml:26-76` declares two application services;
  lines 11-12 require deployment digest pinning. This declaration is not
  evidence that the current candidate ran on those services.
- `git diff --check`: PASS before final report completion.

| #860 acceptance criterion | Result/evidence |
| --- | --- |
| Representative RC workload | **UNVERIFIED** in full: profile lines 167-183 explicitly omit multiple users/Workspaces, Graph fan-out, successful tools/models, Canvas and Goal reconciliation. |
| At least two deployed application replicas | **UNVERIFIED for current RC**: Compose declares two, but executed ASGI tests are not deployment evidence. |
| Sustained saturation/queues/reclaim/retries/leaks/restarts | **UNVERIFIED**: evaluated historical run is only 420.08 s; profile records missing long-window observations. |
| No duplicated physical work across schedule/task/Run/Attempt/Goal | **UNVERIFIED**: historical occurrence Run is cancelled without executing (round30 JSON lines 11-15); unique admissions are not physical-work fencing. |
| Effective rate/security/degraded behavior without replica-selection bypass | **NOT PROVEN**: real middleware regression demonstrates independent allowance; local 429 enforcement does not prove a replica-independent budget. Sustained security/degraded proof remains unverified. |
| PostgreSQL, loop, worker, RSS, fd, queue and error telemetry with thresholds | **UNVERIFIED in full**: profile defines partial thresholds, but driver-loop latency is not application-loop latency and long-window observations are missing. |
| Kill/restart during active work with drain/fencing/recovery | **UNVERIFIED**: historical exit/rejoin and terminal counts do not establish no loss or duplicated physical work; server unit tests are not that experiment. |
| Long-running exact promoted RC/config | **NOT MET by evaluated evidence**: current evaluator rejects duration and artifact; no immutable selected RC/config manifest supplied. |
| File/reclassify findings at earliest broken invariant | Findings retained locally; **external filing/reclassification UNVERIFIED**. GitHub mutations prohibited and not performed. |
| Machine/human evidence tied to promoted hashes | **UNVERIFIED for current RC**: existing JSON names the historical commit above; no new promotion-grade run or promoted image/config identity. |

## Outcome and handoff

**BLOCKED**, not integration approval. Both reported CI failures are absent at
this head. No evidence justifies a vulture ledger or inventory change. The
acceptance block remains; a documentation-only checkpoint cannot resolve it.

Changed file: this report only. No production code, tests, historical evidence,
gates, grants, ledgers or inventory counts changed. No test additions means no
inventory-delta note is required. Existing meaningful regressions ran freshly.

Next: supply/select immutable RC image and configuration identity; complete the
representative enabled-surface workload and application telemetry; reconcile
cross-replica rate-budget behavior through the existing auth/limiter path;
execute the >=4-hour exact-topology soak with canonical Attempt reclaim,
physical-work fencing, Goal reconciliation and active-work recovery observations.
Do not repeat this unchanged preflight as if duration alone could certify an RC.
The server's aiosqlite teardown warning is a residual validation concern, not
newly established production leak evidence. No live soak was attempted here.

Progress: checked 1 issue; done 0 acceptance-complete issues; skipped 0 issues;
blocked 1; failed validation commands 0. This checkpoint is committed locally;
no remote operations or GitHub mutations.
