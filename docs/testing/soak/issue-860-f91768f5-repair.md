# Issue #860 repair — f91768f5

## Frozen scope

- Issue #860 only, branch `auto-860`, clean starting HEAD
  `62867e178c3c821c08d4b74f4a55873d2adf7125`.
- Base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Inspect supplied dispatch, prior result and check-3 log; repository instructions,
  relevant ADRs, `scripts/soak/run_soak.py`,
  `tests/test_soak_promotion_gates.py`, and production paths reached by those probes.
- Candidate edits: this report and `quality/vulture-baseline.json` only if the
  explicitly requested scan identifies reviewed retained debt. Any actual dead
  source will be recorded before changing it. Preserve inherited work.
- No GitHub mutations or develop sync: no conflict exists at start.

## Initial evidence and assumptions

The supplied prior result reports BLOCKED, not acceptance. This job directory
contains no check-*.log files. The supplied historical check-3.log will be read.
The exact promotion RC identity is not specified in the lane prompt; do not
substitute this checkout for the release artifact.

## Fresh checkpoint

The exact vulture command passes: 1323 findings / 1323 reviewed identities,
zero unclassified and never-allowlist findings. No ledger repair is justified.
Historical check-3.log is instead a learning-schema test mismatch (24 versus
21 DDL statements). Fresh targeted validation passes: 37 passed, 6 skipped.
The historical failure does not reproduce. ADR filename `085*` was not found;
not found; skipped rather than guessing another ref. No deployed soak has been
executed.

## Architecture and reachable behavior

Read repository AGENTS.md, docs/README.md, the complete issue body from the supplied
snapshot, the supplied historical failure and prior result, the load profile,
production schema/middleware wiring, driver probes and adjacent tests. Accepted
ADRs 081226-a66b, 081626-f383, 082426-82c7 and 082526-b36a preserve the canonical
`Goal -> Graph -> Run -> NodeRun -> Attempt` model. The later b36a ADR defines
TTL/renewal/reclaim; f383's earlier open boundary is not a reason to introduce
another recovery authority. Occurrence admission is not physical-work uniqueness.

The schema test already lists the three Gauntlet audit columns missing from the
historical failure (`packages/maistro-core/tests/persistence/test_pg_learnings.py:175-179`);
production includes them in `_EPISTEMIC_COLUMNS` and applies the loop inside the
advisory-lock transaction (`packages/maistro-core/src/maistro/persistence/pg_learnings.py:218-226`).
No schema edit is warranted.

## Commands and outcomes

Validation commands used 1200-second timeouts, in the assigned worktree:

| Command | Fresh result |
| --- | --- |
| `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` | PASS: 1323/1323 identities; gate selected trusted base `4aa68edc0b6b` |
| `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py -x -q` | 37 passed, 6 skipped; not live PostgreSQL proof |
| `uv run pytest tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q` | 66 passed |
| `uv run ruff check .` | PASS |
| `uv run ruff format --check .` | PASS: 3270 files |
| `uv run python scripts/check-ratchet-provenance.py` | PASS: 53 consumers; existing invalid-escape SyntaxWarnings |
| `uv run python scripts/check-shipped-surface-truth.py` | PASS |

Gate arguments match `.github/workflows/vulture-ratchet.yml:77-86`.
No flags, authorization grants, baselines or production behavior were changed.

## Acceptance matrix

All ten issue acceptance criteria remain **UNVERIFIED at promotion grade**.
Passing deterministic tests below establish bounded behavior, not a deployed soak.

| Criterion | Executed evidence and outstanding gap |
| --- | --- |
| Representative RC profile | **UNVERIFIED**: `m3a-load-profile.md` records missing multi-user/Workspace, Graph fan-out, successful tool/model, Canvas and background reconciliation workloads. Driver mix at `scripts/soak/run_soak.py:1373-1395` uses one credential and health/task/receipt/metrics requests. No RC configuration was designated in this lane. |
| Two deployed application replicas | **UNVERIFIED**: executed tests use two ASGI apps for real middleware, not two deployed immutable RC replicas. |
| Sustained saturation, queue, lease reclaim, retry and leak observations | **UNVERIFIED**: sampler tests pass, but no sustained production observation window ran. |
| Physical-work uniqueness and Goal reconciliation | **UNVERIFIED**: `scripts/soak/run_soak.py:1044-1069` cancels the admission-probe Run without execution. A unique admission does not prove unique physical effects, Attempt fencing or sustained Goal reconciliation. |
| Replica-selection non-bypass, security and degraded behavior | **UNVERIFIED overall**: fresh `test_replica_selection_has_an_independent_production_allowance` (`tests/test_soak_promotion_gates.py:439`) reproduces `[200,200,429]` separately on both replicas for the same credential/IP. Production installs this middleware at `packages/maistro-server/src/maistro_server/main.py:648`; its documented scope is process-local (`api/rate_limit.py:32-37`). Direct 429 checks cannot prove a shared budget. Acceptance interpretation must be resolved, not silently weakened. |
| Complete telemetry with thresholds | **UNVERIFIED**: sampler records driver-loop lag (`scripts/soak/run_soak.py:1409-1421`), not application event-loop lag; no complete RC pool/lock/query/worker/queue/error series was collected. |
| Active-work restart/drain/fencing/recovery | **UNVERIFIED**: driver exit/rejoin and HTTP counter checks (`scripts/soak/run_soak.py:1428-1487`) lack a physical-effect and stale-worker reconciliation oracle. |
| Long unchanged exact-RC soak | **BLOCKED / UNVERIFIED**: immutable promotion RC/configuration not supplied. `preflight_artifact_check` (`scripts/soak/run_soak.py:730-741`) unconditionally rejects the host-process topology. Fresh tests prove fail-closed rejection even with synthetic four-hour evidence, not a four-hour soak. |
| Load findings filed/reclassified | Local blockers recorded here; external disposition **UNVERIFIED**. GitHub mutations prohibited. No new load run or new load finding claimed. |
| Machine/human evidence tied to image/package/commit/config hashes | **UNVERIFIED**: this commit records local validation only. Historical artifacts were preserved, not relabeled as current RC evidence. |

## Disposition

**BLOCKED** for #860 acceptance, not for a reproducible CI failure. Only this
report changes. No tests added or modified, so no inventory delta note is needed.
No evidence supports a ledger amendment or another schema repair.

Next: supply immutable RC and supported configuration; resolve the replica-local
rate-limit/non-bypass contract; implement representative production-path workload,
physical-effect/recovery oracles and application telemetry using canonical seams;
then execute and retain the long unchanged-RC hash-bound soak. Repeating the stale
schema failure or passing deterministic checks cannot resolve those prerequisites.

Progress: checked 1 issue, done 0 acceptance-complete, skipped 0 issues, errors 0
validation failures. Local report commit is a handoff only, not integration approval.
