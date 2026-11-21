# Issue #860 focused repair — 8726af2b

## Frozen scope

- Only issue #860; branch `auto-860`, clean starting HEAD
  `f34a445cb7d46462336b9f1bbc307fe5f185bea0`; supplied develop base
  `435dc1937e0407ab4de198ffcced49860bb14ad2` resolves locally.
- Inputs: supplied dispatch-context.json (offline snapshot), supplied prior
  result 0218599e, and prior failed check 98a11313/check-3.log. No check logs
  exist in the current job's initial directory snapshot.
- Process the recorded learnings schema test failure, requested exact vulture
  scan, then focused #860 soak acceptance checks. Candidate edit paths are
  this report, `packages/maistro-core/tests/persistence/test_pg_learnings.py`,
  `packages/maistro-core/src/maistro/persistence/pg_learnings.py`,
  `quality/vulture-baseline.json` only for actual reviewed scan findings, and
  `docs/testing/inventory-notes/860-8726af2b-repair.md` if tests change.
- Read surrounding runtime, soak tests/profile and relevant ADRs; no unrelated
  repairs, no GitHub writes, no fetching/re-enumerating campaign items.

## Initial evidence and assumptions

The supplied failure is an exact schema statement-count mismatch (24 actual,
21 expected). It must be reproduced on the starting tree before changing it.
Prior BLOCKED claims are not current validation. No conflict or dirty work
exists to salvage or merge. The unusually large inherited branch diff is
preserved, not treated as authorization to repair unrelated packages.

Assumption: this is a writer repair, not the read-only verifier role. The
explicit CI-repair exception permits a ledger amendment only if the exact
scan identifies retained identities. RC promotion cannot be claimed from
unit tests or host preflight evidence.

## Recorded validation

- Exact requested vulture command PASS: 1323 findings / 1323 reviewed identities,
  zero unclassified or forbidden findings; selected ratchet base `4aa68edc0b6b`.
  Log: `/tmp/860-8726af2b-vulture.log`. No ledger edit is justified.
- `uv run pytest packages/maistro-core/tests/persistence/test_pg_learnings.py tests/test_soak_promotion_gates.py packages/maistro-server/tests/api/test_tasks_concurrency_backpressure.py -x -q`:
  **103 passed, 6 skipped**, 2.47 seconds. Log: `/tmp/860-8726af2b-tests.log`.
  The prior schema mismatch does not reproduce: the current test independently
  expects the three validation audit columns present in production. No test
  weakening or redundant schema repair is warranted. Skips are not DB evidence.
- `uv run ruff check .`: PASS (`/tmp/860-8726af2b-ruff.log`).
- `uv run ruff format --check .`: PASS, 3270 files
  (`/tmp/860-8726af2b-format.log`).
- `uv run python scripts/check-deployment-claims.py`: PASS
  (`/tmp/860-8726af2b-deployment.log`).
- `uv run python scripts/check-execution-lifecycles.py`: PASS, 19 classified
  lifecycles (`/tmp/860-8726af2b-lifecycles.log`).
- Validation commands used 1200-second timeouts. Vulture arguments match
  `.github/workflows/quality.yml` and `vulture-ratchet.yml`.

## Production reachability and architecture

Read repository instructions and the documentation authority map, ADR-081
(Proposed, not an accepted override), ADR-085, ADR-081426-1f7c and
ADR-082526-b36a (Accepted). The canonical execution model remains
`Goal -> Graph -> Run -> NodeRun -> Attempt`. Physical execution identity is
Attempt; receipt deduplication is insufficient evidence of physical effect
uniqueness. Recovery must honor canonical lease renewal and fencing, not
infer every active worker dead when another replica restarts.

`packages/maistro-server/src/maistro_server/main.py:648` installs the real
rate middleware. Its constructor at `api/rate_limit.py:95` creates a separate
in-memory limiter. The freshly executed test at
`tests/test_soak_promotion_gates.py:439` observes `[200, 200, 429]` on each of
two instances for the same identity, with and without authentication. Thus
replica selection increases aggregate allowance; direct-replica 429 probes
prove local enforcement, not a shared budget. ADR-085 mandates principal
identity but does not specify shared state: no ADR waiver of #860's stronger
non-bypass acceptance is established. Do not invent an authorization path to
resolve this ambiguity in a CI-ledger repair.

The task backpressure test executes the real router and canonical in-memory
Run spine: a full ceiling returns 429 with Retry-After, a different principal
still admits, and releasing a slot restores admission. Production translates
`RunConcurrencyExceeded` at `api/tasks.py:117`. This proves that boundary,
not multi-replica PostgreSQL admission or physical execution.

## Acceptance matrix (all ten issue criteria)

| Criterion | Executed evidence and remaining gap |
| --- | --- |
| Representative RC workload | **UNVERIFIED**. `m3a-load-profile.md:152` acknowledges missing users/Workspaces, Graph fan-out, successful tool/model, Design/Canvas and Goal/background workloads. RC-specific applicability is not designated. |
| At least two deployed application replicas | **UNVERIFIED**. Two actual limiter instances exercised by ASGI tests are not two deployed RC replicas. |
| Sustained saturation/queue/reclaim/retry/leak/shutdown observations | **UNVERIFIED**. Sampler test exercises a real uv child and sees RSS/fd growth, but no sustained RC workload was executed. |
| No duplicate physical work across replicas | **UNVERIFIED**. HTTP probe tests reject missing/duplicate receipt identities; mocks and unique Run receipts do not prove physical Attempt effect fencing. |
| Replica-selection non-bypass and security/degraded behavior | Shared allowance interpretation is **falsified** by executed production middleware tests above. Full deployed security criterion **UNVERIFIED**. Production admission backpressure regression passes. |
| Complete metrics with explicit thresholds | **UNVERIFIED at RC grade**. Profile has thresholds, but driver-loop sampling is not application-loop latency and no sustained RC saturation/lease observations exist for this validation. |
| Kill/restart during active work with drain/fencing/recovery | **UNVERIFIED**. Boot-cleanup regressions pass, not evidence of active physical-work recovery. |
| Long-running exact RC/configuration | **UNVERIFIED / BLOCKED**. `scripts/soak/run_soak.py:730` explicitly rejects its host preflight as exact RC evidence. Executed CLI tests fail closed even for synthetic four-hour evidence. |
| Findings filed/reclassified before promotion | **UNVERIFIED externally**. Findings recorded here; no GitHub mutations permitted or performed. |
| Machine/human evidence bound to exact artifact/config hashes | **UNVERIFIED for RC**. This report names the checked source HEAD, not a promoted image/configuration or long-soak evidence pack. |

The frozen parent #89 body requires an identical tested RC, real-model,
security and recovery validation. Neither that body nor the captured draft
PR #1672 body designates the immutable artifact/configuration. Local HEAD is
not assumed to be the promotion candidate. Existing evidence and inherited
branch changes are preserved but are not certified by this focused run.

## Handoff

**BLOCKED** on release prerequisites, not a sync conflict or reproduced CI
failure. No code, tests, gates or ledgers changed; inventory delta is zero,
so no inventory note is required. Only this report is added and committed.

Required next input: designate immutable RC image/package and runtime config,
justify representative workload scope, and settle the replica-selection rate
budget requirement. Then execute the exact production topology long soak
with physical Attempt-effect correlation, complete telemetry and active-work
recovery. Repeating the already-passing schema/vulture checks cannot supply
those missing release inputs.

Progress: checked 1 issue; done 0 acceptance-complete issues; skipped 0;
errors 0 fresh validation commands; next: RC designation and production soak.
Local commit is a blocked handoff, never integration or promotion approval.
