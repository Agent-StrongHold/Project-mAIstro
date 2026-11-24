# #1064 follow-up verification (2026-11-23)

This verification does not add tests or claim issue closure. It records checks
run against `db22f8bb9433022c912b5644733bd701445180d0` and the acceptance gaps
that remain visible in production code.

## Executed

- `uv run pytest packages/hive-conductor/backend/tests/test_evolution_restart_replay.py packages/hive-conductor/backend/tests/test_evolution_restart_replay_pg.py -x -q`
  -> **16 passed, 10 skipped**. PostgreSQL was not configured (`MAISTRO_TEST_PG_DSN` unset), so the PG legs are not evidence for PostgreSQL recovery.
- `uv run ruff check . && uv run ruff format --check .` -> passed (3,650 files formatted).
- CI-exact acceptance-state ratchet:
  `uv run python scripts/check-ac-state.py --run-tests --ratchet --mandate 88ca7a1ccb5cc1fca7f0d2fa51f2527b1a2b918f`
  -> **failed**, design coverage `39.7781%` below the base floor `44.4608%`.
  No authorization or quality-ledger change was made.

## Acceptance remains unproven

- `services/evolution_graph.py::_recovery_resolver` (around lines 1480-1503)
  explicitly states that the production `PopulationStore`/`EloTournament` are
  not durably reconstructible in a new process; it refuses recovery instead
  of satisfying restart/resume.
- The `recover_queued_graph_runs` path can leave a candidate QUEUED on an
  eager resolver failure (documented in the same resolver docstring), so an
  explicit terminal/blocked disposition for missing prerequisites is not
  established.
- The replay tests reopen stores in one Python process; no distinct-OS-process
  Run-level launch is exercised. The scoped run above also skipped the PG
  cases, and does not prove the required PostgreSQL parity.
- The existing fault cases do not inject faults after every cull/breed/
  migrate/self-improve/finalize publication boundary. Exact production-harness
  parity, stale-fence concurrent publication, and uninterrupted-versus-
  process-kill population/lineage equivalence remain unverified.

The SQLite passing cases show the narrower receipt behavior exercised by those
tests only. This note does not upgrade that evidence to the issue's close-only
bar or assert remote exact-head CI / #947 review disposition.

## Re-verification at `f264d5eeb392cb698ac5dae9e03ef7042e4a9623` (2026-11-23)

Corrects the ratchet record above: the earlier acceptance-state "failure" was
an environment artifact, not a branch defect. CI's `Quality / Acceptance state`
job runs with a pgvector service and `MAISTRO_TEST_PG_DSN`/`DATABASE_URL` set
(quality.yml:2367-2392) before invoking the gate; the earlier run reused CI's
command without CI's service, so the PostgreSQL legs did not execute and
design coverage landed at `39.7781%`.

Executed this round (postgres `pgvector/pgvector:pg18` on `127.0.0.1:5570`,
`alembic upgrade head` applied first):

- `uv run pytest packages/hive-conductor/backend/tests/test_evolution_restart_replay.py
  packages/hive-conductor/backend/tests/test_evolution_restart_replay_pg.py -q`
  -> **26 passed** (16 same-interpreter legs + 10 PostgreSQL legs against the
  real server). The PG recovery/idempotency legs pass; they were never seen
  running in earlier rounds.
- CI-exact `uv run python scripts/check-ac-state.py --run-tests --ratchet
  --mandate 88ca7a1ccb5cc1fca7f0d2fa51f2527b1a2b918f` with CI's PG env
  -> **exit 0**; design coverage sits exactly on the banked floor `44.4608%`,
  every declared criterion proven, no chain regressions. Run twice, ~2 min.
- `ruff check` / `ruff format` / suite-inventory gates: passed (driver logs).

The close-only gaps are unchanged by this head (docs-only delta):

- No distinct-OS-process Run-level launch: kills are in-interpreter
  `_ProcessKilled` and `_restore_process` re-enters the same interpreter;
  `test_evolution_restart_replay_pg.py:7-11` states this is not evidence for
  the distinct-process requirement.
- PG legs run `harness=SimpleNamespace(fidelity="proxy")` (lines 207, 237,
  331) and populations arrive pre-scored, so production-harness byte/semantic
  parity is not established.
- `_config()` pins `cull_pct=0.0` / `migration_interval=1000` and
  `_self_improve_top` is a no-op, so no fault is injected after the cull,
  migrate, or self-improve publication boundaries.
- The stranded-QUEUED disposition stays QUEUED by design
  (`test_evolution_recovery.py:460-505`), which does not satisfy the
  criterion requiring an explicit terminal/recovery-blocked disposition for
  prerequisites that never become durable.
- The production service restores its Evolve domain from the durable store at
  startup (`services/evolution.py::restore_or_initialize_domain_state`), so
  the earlier claim that `_recovery_resolver` categorically refuses genuine
  new-process recovery was overstated. What remains unproven is end-to-end
  Run-level recovery from a distinct OS process using the production startup
  path; the current replay test reconstructs a service object in-process.
- #947 P1 threads show no explicit disposition in the snapshot; remote
  exact-head CI remains UNVERIFIED (rollup empty at capture). Branch commits
  and the #2497 body carry no fixes/closes/resolves keywords.

## Re-check at `53a4c4d8a55d7c2c9b882e2a09c280c547c2827d` (2026-11-23)

- Re-ran the restart replay suites: `16 passed, 10 skipped`; PostgreSQL was
  unavailable in this environment, so skipped PG cases are not acceptance
  evidence.
- Targeted `ruff check` for the replay implementation/tests passed.
- No test or production-code change in this round. The remaining distinct
  process, publication-boundary, production-harness parity, queued disposition,
  #947 review-disposition, and exact-head CI gaps above are not repaired here.

## Independent verification at `3e2c77c65f05c53c70dae9cb78800502d78cc682` (2026-11-23)

Corrects the previous section: PostgreSQL **was** reachable this round
(`maistro-1064-pg`, migrated `alembic_version=069`), so the PG legs executed
for real. Executed by the verifier, not inferred:

- `MAISTRO_TEST_PG_DSN=postgresql://maistro:maistro@localhost:5570/maistro_test
  uv run pytest packages/hive-conductor/backend/tests/test_evolution_restart_replay.py
  packages/hive-conductor/backend/tests/test_evolution_restart_replay_pg.py
  packages/hive-conductor/backend/tests/test_evolution_startup_wiring.py
  packages/hive-conductor/backend/tests/test_evolve_domain_retention.py
  packages/hive-conductor/backend/tests/test_evolve_domain_store.py
  packages/hive-conductor/backend/tests/test_evolution_recovery.py -q`
  -> **67 passed, 0 skipped**. Includes the Run-level PostgreSQL legs, the
  sqlite restart-replay legs, and the genuine-subprocess publication-ledger
  fence (`test_evolve_domain_store.py`: a distinct OS process INSERTED a
  battle publication and the parent process observed exactly one row and got
  FENCED on re-publication).
- Without the DSN the same five conductor files give 40 passed / 13 skipped
  (matches the driver's deterministic check), and the two replay files alone
  give the 16 passed / 10 skipped recorded above.
- `uv run ruff check .` -> passed; suite-inventory gates for
  `packages/hive-conductor/backend/tests` (4528 node IDs) and
  `packages/maistro-evolve/tests` (1017 node IDs) -> ok.
- Remote exact-head CI refresh (`gh pr view 2497`, read-only): 65 checks
  COMPLETED, 14 IN_PROGRESS (`test`, `coverage (PostgreSQL)`,
  `integration-scope`, `Gate C`, e2e, postgres pg17/pg18, container scan),
  0 observed failures -> exact-head CI remains **UNVERIFIED** until the
  rollup settles green at this SHA.
- `pulls/947/reviews` snapshot: 7/7 COMMENTED, none APPROVED -> the
  close-only review-disposition criterion is still unmet.

The delta `53a4c4d8a55d..3e2c77c65f05c` is docs-only (this note). None of the
enumerated close-only gaps — distinct-OS-process Run-level launch,
publication-boundary fault injection breadth, production-harness parity,
explicit terminal disposition for never-durable prerequisites, approved
design + #947 disposition, exact-head CI — is repaired at this head.

## Independent re-check at merged head `026cad5db51f` (2026-11-23)

Lane re-verification after `origin/develop` was merged in (`8e7d7d3165`,
delivery-planner tooling; no #1064 code in that side). Delta
`3e2c77c65f05c..026cad5db51f` is docs-only for #1064 plus the unrelated
develop merge, so every gap above carries over unchanged. Re-executed, not
inferred:

- `MAISTRO_TEST_PG_DSN=postgresql://maistro:maistro@localhost:5570/maistro_test
  uv run pytest packages/hive-conductor/backend/tests/test_evolution_restart_replay.py
  packages/hive-conductor/backend/tests/test_evolution_restart_replay_pg.py
  packages/hive-conductor/backend/tests/test_evolution_startup_wiring.py
  packages/hive-conductor/backend/tests/test_evolve_domain_retention.py
  packages/hive-conductor/backend/tests/test_evolve_domain_store.py
  packages/hive-conductor/backend/tests/test_evolution_recovery.py -q`
  -> **67 passed, 0 skipped** at `026cad5db51f` (`maistro-1064-pg` still up,
  migrated to `alembic_version=069`). Matches the `3e2c77c65f05c` result.
- Driver deterministic checks at this head: `uv run ruff check .` and
  `ruff format --check` clean; maistro-evolve replay suites 11 passed;
  conductor suites without DSN 40 passed / 13 skipped; suite-inventory gates
  ok (hive-conductor backend 4528 node IDs, maistro-evolve 1017).
- Closure-keyword scan of `git log 8e7d7d3165..HEAD --format='%s%n%b'`: no
  `fixes/closes/resolves #N` (conventional `fix(#1064):` prefixes only).
- Live CI refresh at this exact SHA (`gh pr view 2497`, read-only): 63
  COMPLETED/SUCCESS + 2 SKIPPED, but **14 IN_PROGRESS** (`test`,
  `coverage (PostgreSQL)`, `coverage (no services)`, `coverage (MinIO)`,
  `integration-scope`, `Container scan + SBOM + cosign`,
  `docker-rebuild-compare`, `postgres (pg17)`, `postgres (pg18)`,
  `hive-conductor-e2e-ui`, `hive-conductor-e2e`,
  `hive-conductor-compose-durability`, `docker-build`,
  `Quality / Acceptance state`) -> exact-head CI still **UNVERIFIED**.
- Prior-finding evidence re-confirmed at this head:
  `test_evolution_restart_replay.py` `:57-58` (`_ProcessKilled` BaseException,
  in-interpreter), `:307-309` (`_self_improve_top` no-op), `:315-317`
  (`cull_pct=0.0`, `migration_interval=1000`), `:377-380` (`_restore_process`
  docstring admits the missing subprocess Run-level test), `:445-456`
  (`_bind_deterministic_harness` replaces `EvalHarness`);
  `test_evolution_restart_replay_pg.py:4-9` (same-OS-process admission) and
  `:207,237,331` (`fidelity="proxy"`); `test_evolution_recovery.py:460-505`
  (never-durable prerequisites stay QUEUED by design); no `docs/adr` or
  `docs/specs` path in `git diff 8e7d7d3165..HEAD`; `pulls/947/reviews`
  snapshot 7/7 COMMENTED.

Verdict carried at this head: **NEEDS-REPAIR** — the implementation and its
PG legs are genuinely green locally, but the issue's close-only contract
(distinct-OS-process Run-level launch, cull/migrate/self-improve boundary
fault injection, production-harness parity, explicit terminal disposition for
never-durable QUEUED prerequisites, approved persistence/replay design +
#947 review disposition, exact-head green CI, #459 strict-scenario coverage)
is not yet satisfied.

## Independent verification at exact head `dfd2464c5e49fe235ebb8df3453afb9023f216b3` (2026-11-23)

Verifier-executed at the assigned head (delta `026cad5db51f..dfd2464c5e` is
this docs note only; no code or test change). Re-derived, not inferred:

- `MAISTRO_TEST_PG_DSN=postgresql://maistro:maistro@localhost:5570/maistro_test
  uv run pytest test_evolution_restart_replay.py test_evolution_restart_replay_pg.py
  test_evolution_startup_wiring.py test_evolve_domain_retention.py
  test_evolve_domain_store.py test_evolution_recovery.py -q`
  -> **67 passed, 0 skipped** against `maistro-1064-pg` (alembic_version=069).
- `uv run pytest packages/maistro-evolve/tests/test_domain_reconstruction.py
  packages/maistro-evolve/tests/test_durable_snapshot.py -q` -> **11 passed**.
- `uv run pytest tests/cross_product_parity/test_cross_product_parity.py -q`
  -> **26 passed**.
- `uv run ruff check .` -> all checks passed; `uv run python
  scripts/check-suite-inventory.py` (CI's exact no-arg invocation) -> ok,
  21 suites match the recorded inventory.
- Live read-only `gh pr view 2497` at this exact head: rollup shows 79 checks
  with no terminal state plus 1 PENDING (`test`, `coverage (PostgreSQL)`,
  `integration-scope`, `Gate C`, `formal-conformance`, `Mutation gate`,
  SAST family, `cross-product-parity`, ... unsettled) -> exact-head CI
  remains **UNVERIFIED**.
- Closure-keyword scan of `git log 88ca7a1ccb..HEAD --format='%B'`: no
  fixes/closes/resolves #N; conventional `fix(#1064):`/`docs(#1064):`
  prefixes only.
- All prior evidence re-confirmed at this head: `_ProcessKilled(BaseException)`
  in-interpreter kill (`test_evolution_restart_replay.py:56-58`),
  `_restore_process` same-interpreter docstring (:377-380),
  `cull_pct=0.0`/`migration_interval=1000` (:315-317) with `_self_improve_top`
  no-op (:307-309), `_bind_deterministic_harness` EvalHarness double
  (:445-456), PG suite same-OS-process header
  (`test_evolution_restart_replay_pg.py:4-9`) with `fidelity="proxy"` harness
  (:207,237,331), stranded runs left QUEUED by design
  (`test_evolution_recovery.py:455-510`), no `docs/adr` or `docs/specs` path
  in `git diff 8e7d7d3165..HEAD`, and `pulls/947/reviews` 7/7 COMMENTED
  (dispatch-context.json).

Verdict at this head: **NEEDS-REPAIR** — locally green and genuinely
PG-backed, but the issue's close-only contract and the cull/migrate/
self-improve boundary, never-durable-prerequisite disposition, harness-parity,
approved-design/#947-disposition, and exact-head-CI criteria remain unmet
(as itemized above). Repair budget for this campaign is exhausted; these
findings are handed off unresolved.

## Re-check at assigned head `2238ef039c44b471813114af983a35acae62974b` (2026-11-23)

The job directory supplied no `check-*.log` files, so there was no driver log
set to inspect. Re-ran the directly relevant suite rather than relying on
prior claims:

- `uv run pytest packages/hive-conductor/backend/tests/test_evolution_restart_replay.py packages/hive-conductor/backend/tests/test_evolution_restart_replay_pg.py -x -q`
  -> **16 passed, 10 skipped** (the skip is the optional PostgreSQL legs
  without `MAISTRO_TEST_PG_DSN`).
- With `MAISTRO_TEST_PG_DSN=postgresql://maistro:maistro@localhost:5570/maistro_test`,
  the same command -> **26 passed, 0 skipped** against the configured
  `maistro-1064-pg` service.
- Targeted `uv run ruff check` over the touched replay service/test modules
  -> passed.

This establishes the current replay tests locally, including their live-PG
legs, but does not remedy their stated limits: PostgreSQL recovery is still
same-OS-process, the test harness is proxy/pre-scored, cull/migrate/self-
improve boundaries are not faulted, and queued resolver failures are not
terminalized. No production or test code was changed in this round. The
approved design/#947 disposition and hosted exact-head CI are also outside
this local evidence; exact-head CI remains **UNVERIFIED**. Verdict remains
**NEEDS-REPAIR**.

## Writer re-check at assigned head `586a60696248` (2026-11-23)

No `check-*.log` files were present in the assigned job directory. Re-ran the
local replay/recovery suites without a PostgreSQL DSN:

- `uv run pytest packages/hive-conductor/backend/tests/test_evolution_restart_replay.py packages/hive-conductor/backend/tests/test_evolution_restart_replay_pg.py packages/hive-conductor/backend/tests/test_evolution_recovery.py -x -q`
  -> **30 passed, 10 skipped**. The skipped PostgreSQL cases do not establish
  PG crash/restart behavior.
- `MAISTRO_TEST_PG_DSN` was unset; no PostgreSQL acceptance claim is made.

No production or test change was made: the prior evidence still identifies
unresolved actual-process Run recovery, finalization boundary coverage,
production harness parity, and the queued prerequisite disposition. This
verification-only entry adds no tests and makes no inventory-count claim.
The approved design/#947 disposition and exact-head hosted CI remain
unverified. Verdict: **NEEDS-REPAIR**.

## Writer re-check at assigned head `bcf4141811f3` (2026-11-23)

The assigned job directory contained no `check-*.log` files, so I did not rely
on driver claims. Re-ran the focused restart/recovery suite:

- `uv run pytest packages/hive-conductor/backend/tests/test_evolution_restart_replay.py packages/hive-conductor/backend/tests/test_evolution_restart_replay_pg.py packages/hive-conductor/backend/tests/test_evolution_recovery.py -x -q`
  -> **31 passed, 10 skipped**. `MAISTRO_TEST_PG_DSN` was unset; the skipped
  PostgreSQL legs do not prove live-PG recovery.
- `uv run ruff check . && uv run ruff format --check .`
  -> passed; 3,652 files already formatted.

These results validate the available SQLite/in-process test paths only. The
committed-finalize test at `test_evolution_restart_replay.py:1209` kills after
both committed snapshot and marker, so it does not cover snapshot-persisted /
marker-pending. The recovery test at `test_evolution_recovery.py:488` continues
to assert a mismatched-prerequisite Run remains QUEUED; this is inconsistent
with issue #1064's explicit no-indefinite-QUEUED requirement. The test harness
also remains same-interpreter and does not inject after cull, breed, migrate,
or real self-improvement. No claim of distinct-process or actual PostgreSQL
acceptance is made. The approved persistence/replay design, #947 P1 disposition,
and exact-head hosted CI remain unverified. No test was added and no inventory
count changed. Verdict: **NEEDS-REPAIR**.

## Writer validation at assigned head `bf53e2d40b44` (2026-11-23)

No `check-*.log` files were present in the job directory. Inspected the new
accepted operational recovery contract in `docs/adr/ADR-088-maistro-evolve-experimental.md`
and the new boundary-fault / distinct-process test cases rather than relying
on earlier verification claims. Executed:

- With `MAISTRO_TEST_PG_DSN=postgresql://maistro:maistro@localhost:5570/maistro_test`,
  `uv run pytest` on the Evolve restart/replay, startup wiring, retention,
  durable-store, recovery, package snapshot/reconstruction, and cross-product
  parity suites -> **116 passed, 0 skipped**. This includes the PG restart and
  child-process legs against the local `maistro-1064-pg` service.
- `uv run ruff check .` -> passed; `uv run ruff format --check .` -> passed
  (3,652 files).
- `uv run python scripts/check-suite-inventory.py` -> passed (21 suites).
- `uv run python scripts/check-ac-state.py --run-tests --ratchet --mandate
  88ca7a1ccb5cc1fca7f0d2fa51f2527b1a2b918f` with the PG DSN -> passed; design
  coverage 44.4608% at the mandated floor, all declared criteria proven.
- `uv run pytest tests/migrations/test_migration_chain.py -x -q` -> 18
  skipped; migration-chain acceptance was not exercised by this command.

The added ADR resolves the previously noted missing in-tree design record;
the new tests address snapshot-before-marker, real finalization mutation
boundaries, and a distinct child-process PG recovery leg. The suite does not
by itself prove live hosted exact-head CI or an explicit disposition of the
#947 review threads. Those close-only items remain **UNVERIFIED**. No tests
were added during this verification update, so suite inventory counts did not
change.

## Writer validation at assigned head `595ea0f4fe84` (2026-11-23)

Revalidated locally rather than relying on the prior attempt's report. The
focused PostgreSQL-enabled restart/replay command
`MAISTRO_TEST_PG_DSN=postgresql://maistro:maistro@localhost:5570/maistro_test
uv run pytest packages/hive-conductor/backend/tests/test_evolution_restart_replay.py
packages/hive-conductor/backend/tests/test_evolution_restart_replay_pg.py -x -q`
passed (**38 passed, 0 skipped**), including the distinct-subprocess PG
recovery and finalize-boundary tests. `uv run ruff check .`,
`uv run ruff format --check .`, and `uv run python
scripts/check-suite-inventory.py` passed; inventory reports 21 suites with no
delta. No test was added in this update.

The design/recovery contract and local behavioral evidence are in-tree, but
this does not satisfy the full close-only contract: hosted exact-head CI still
has pending/in-progress checks, and dispatch evidence shows no explicit
#947 review disposition. Both are **UNVERIFIED** and cannot be manufactured by
local code edits. Verdict: **NEEDS-REPAIR**.

## Independent verification at exact head `ce5a1502b366abbcf46be119d91bd76c22e0a5bf` (2026-11-23)

Re-derived from the issue text, not inherited from prior summaries. Executed by
the verifier at this head (`maistro-1064-pg` on `127.0.0.1:5570`,
`alembic_version=069`):

- `MAISTRO_TEST_PG_DSN=postgresql://maistro:maistro@localhost:5570/maistro_test
  uv run pytest packages/hive-conductor/backend/tests/test_evolution_restart_replay.py
  packages/hive-conductor/backend/tests/test_evolution_restart_replay_pg.py
  packages/hive-conductor/backend/tests/test_evolution_startup_wiring.py
  packages/hive-conductor/backend/tests/test_evolve_domain_retention.py
  packages/hive-conductor/backend/tests/test_evolve_domain_store.py
  packages/hive-conductor/backend/tests/test_evolution_recovery.py
  packages/maistro-evolve/tests/test_domain_reconstruction.py
  packages/maistro-evolve/tests/test_durable_snapshot.py
  tests/cross_product_parity/test_cross_product_parity.py -q`
  -> **116 passed, 0 skipped in 39s**, including the distinct-OS-process
  PostgreSQL recovery leg (`test_evolution_restart_replay_pg.py:486` child
  interpreter, `pid != parent`, battle/Elo/population snapshot equality vs the
  uninterrupted reference) and the per-boundary finalize fault parametrization
  (`test_evolution_restart_replay.py:1524` cull/breed/self_improve/migrate with
  every boundary active: `_config()` cull_pct=0.25, island_count=2,
  migration_interval=1; self-improve mutates before its kill seam).
- `uv run ruff check .` -> passed. Driver deterministic checks at this head
  (job check-*.log): `ruff format --check` clean (3,652 files), maistro-evolve
  replay suites 11 passed, conductor subset 46 passed / 19 skipped without DSN,
  suite-inventory gates ok (hive-conductor backend 4540, maistro-evolve 1017).
- Delta `595ea0f4fe84..ce5a1502b366` is docs-only (the previous section below);
  no production or test code changed since the last validated head.
- Closure-keyword scan: `git log a6a0969ca1..ce5a1502b366 --format='%s%n%b'`
  -> no fixes/closes/resolves #N (34 commits); live PR #2497 body also clean
  ("Refs #1064" only). PR headRefOid equals this exact SHA.

Newly verified this round (read-only live GitHub):

- **#947 P1 review disposition now exists.** All 7 review threads checked via
  GraphQL: 6/7 RESOLVED, and the resolved set includes **all four P1 threads**
  ("Register a restart path", "Make tournament battle ...", "Make cycle
  finalization ...", "Preserve evolution when ..."). One **P2** thread remains
  unresolved (`PRRT_kwDOT-he_M6d9dTY`, "Record the durable executor on admitted
  Evolve runs" — executor provenance marker). The issue's disposition criterion
  is P1-specific and is met; the open P2 is recorded as residual, outside this
  issue's close-only text.
- **Exact-head hosted CI remains UNVERIFIED.** Two earlier rollup readings were
  taken while the PR head still moved: 66 COMPLETED/SUCCESS + **11 IN_PROGRESS**
  at `15941a6e22`, then 69 COMPLETED + 10 IN_PROGRESS + 1 null-status at
  `9ef6fb4e14` — neither was the final head, so neither counts as exact-head
  evidence. Fresh live reading this round: `gh pr view 2497` headRefOid now
  equals the final head `4d9ef50dd1`; its run (started 2026-11-23T22:32:41Z,
  80 checks) shows **58 SUCCESS, 18 IN_PROGRESS, 2 SKIPPED, 1 NEUTRAL
  (CodeQL), 0 failures** at last refresh. The run is at the exact SHA but
  still in flight: pending CI is not green, and the close-only exact-SHA/CI
  criterion stays UNVERIFIED until this rollup settles with no failures at
  this SHA.
- **The `#459` strict-scenario criterion has in-tree evidence at this head.**
  `tests/cross_product_parity/test_cross_product_parity.py::test_evolve_required_scenario_emits_strict_closeout_evidence`
  runs the shipped canonical evolution cycle through the durable graph with the
  durable Evolve domain store, then checks Conductor inspection evidence,
  exactly-once publication, and foreign-reference refusal. The test/harness
  name `#459` (`tests/cross_product_parity/harness.py:250`);
  abstention fails closed. This exact-head test passed in 1.13s. This supersedes
  the earlier statement above that no such evidence exists.

Verdict carried at this head: **NEEDS-REPAIR** — locally executable acceptance
criteria pass with real PostgreSQL at this exact SHA (including distinct-process
recovery, per-boundary finalize fault injection, exactly-once publication
fences, honest refusal windows, and the #459 strict scenario); the #947 P1
disposition is met. Hosted exact-head CI remains unverified and requires
settlement on PR #2497 outside this worktree.

## Round 4 — head `31c38337db1d` (2026-11-23T22:5xZ, independent verifier re-run)

The assigned head is the round-3 writer commit `31c38337db1d`; the delta from
the previously code-validated head `4d9ef50dd1` is docs-only
(`git diff --stat 4d9ef50dd1..HEAD`: this note only), so all production-code
evidence above carries over verbatim.

Re-executed at this exact head (not trusted from prior rounds):

- Driver deterministic checks (job `3491434d…` check-*.log, all rc=0):
  `uv sync --locked --extra dev`; `ruff check .`; `ruff format --check` clean
  (3,652 files); maistro-evolve replay suites 11 passed; conductor subset
  46 passed / 19 skipped without DSN; suite-inventory gates ok
  (hive-conductor backend 4540 node IDs, maistro-evolve 1017).
- **PG acceptance legs re-run by this verifier with
  `MAISTRO_TEST_PG_DSN=postgresql://maistro:maistro@127.0.0.1:5570/maistro_test`
  (PG18 container, alembic `069`): 65 passed, 0 skipped** — the 19 DSN-gated
  legs now actually executed, including the distinct-OS-process recovery leg
  (`test_evolution_restart_replay_pg.py:486`, real `subprocess.run` child,
  asserts `pid != os.getpid()` and exact battle/Elo/population parity vs the
  uninterrupted reference) and the per-boundary finalize fault parametrization
  (`test_evolution_restart_replay.py:1524`, cull/breed/self_improve/migrate,
  byte-identical via `export_genomes_snapshot()`/`_domain_signature()`).
- `tests/cross_product_parity/test_cross_product_parity.py::
  test_evolve_required_scenario_emits_strict_closeout_evidence` — 1 passed in
  1.23s at this head.
- `packages/maistro-evolve/tests/test_domain_reconstruction.py +
  test_durable_snapshot.py` — 11 passed.
- **#947 P1 disposition re-checked live** (GraphQL reviewThreads): 4/4 P1
  threads `isResolved=true`; 6/7 threads resolved; the one open thread is the
  **P2** residual `PRRT_kwDOT-he_M6d9dTY` ("Record the durable executor"),
  unchanged and outside this issue's P1-specific criterion.
- **Closure-keyword scan** `git log a6a0969ca1..31c38337db1d --format='%s%n%b'`
  for GitHub closure syntax (`keyword ␣ #N`): **no matches**. The
  conventional-commit `fix(#1064):` prefixes are not closure syntax (no
  whitespace between keyword and reference); live PR #2497 body contains only
  "Refs #1064".

Exact-head hosted CI readings this round (`gh pr view 2497`, headRefOid ==
`31c38337db1d`): first refresh 80 checks — 61 SUCCESS / 2 SKIPPED /
16 IN_PROGRESS / 1 null / **0 failures**; second refresh (≈4 min later) —
**71 SUCCESS / 2 SKIPPED / 7 IN_PROGRESS / 1 null / 0 failures** (coverage,
integration-scope, e2e, container scan, docker-build, `test`, and one
unstarted context still settling). The rollup is at the exact SHA, never
failed, and still in flight: pending CI is not green, so the close-only
exact-SHA/CI criterion remains **UNVERIFIED until it settles with no
failures**.

Verdict carried at this head: **NEEDS-REPAIR** (single open criterion:
hosted exact-SHA CI settlement) — every locally executable acceptance leg was
re-executed and passed at this exact SHA with real PostgreSQL.

### Round 4 addendum — exact-head CI settled RED (2026-11-23T23:0xZ)

The in-flight rollup at this head **settled with a completed FAILURE**, so the
exact-SHA/CI criterion is now definitively unmet (no longer merely "pending"):

- Check `Coverage gate (publish-set floor + diff coverage)` — job
  `138078750667`, run `45282026375`, completed 2026-11-23T23:01:11Z:
  `Coverage failure: total of 83 is less than fail-under=87` →
  `##[error]publish-set coverage below the 87% floor` (TOTAL 110,859
  statements / 17,046 missed = 83%).
- Not a partial-artifact race: the gate `needs: [coverage-unit,
  coverage-archive, coverage-postgres]` (`.github/workflows/quality.yml:540`)
  and its runner setup began only after the producers completed (23:00:36Z);
  the combine ran over full artifacts.
- Not pre-existing red on the base: develop's latest quality run
  `45239478051` at `a6a0969ca1` (the merge base) concluded **success** at
  2026-11-23T18:32:28Z — the branch's diff is what turned the gate red.
- Branch-relevant change: this PR's additive coverage producer step
  (`.github/workflows/quality.yml:498-518`, "hive-conductor Evolve PostgreSQL
  legs (under coverage)") deliberately extends what the combine measures for
  `packages/hive-conductor/backend/services`; the step's own comment records
  the store's changed lines measuring 85% pre-existing. The publish-set floor
  arithmetic now lands below 87% with the branch's ~2.5k lines of backend
  service code (evolve_domain_store.py +858, evolution_graph.py +624/-39,
  evolution.py +335) in scope. Whether the repair is (a) more covered arcs for
  the new code in the recorded producers, (b) a floor re-authorization under
  the quality-gates grant process (two merges), or (c) producer-set scoping,
  is a repair-lane decision — the verifier does not adjust floors.
- Last rollup reading (2026-11-23T23:5xZ): 77 SUCCESS / 2 SKIPPED /
  1 IN_PROGRESS (`test`) / **1 FAILURE (Coverage gate)** / 1 null context.

Verdict for this round: **NEEDS-REPAIR** — locally executable acceptance legs
all re-executed and passed at this exact SHA with real PostgreSQL, #947 P1
disposition met, no premature closure keywords; but the close-only
exact-SHA/CI criterion now fails concretely at the head (coverage gate FAILURE,
branch-attributable vs a green develop base).

## Round 5 — head `0389a4797f99` (2026-11-23T23:4xZ, independent verifier re-run)

The assigned head is one docs commit past the round-4 head: `git diff --stat
31c38337db1d..0389a4797f99` = this note only (+89 lines). No production or
test code changed, so the round-4 hosted findings below carry over at equal
code content.

Re-executed at this exact head (not trusted from prior rounds):

- Driver deterministic checks (job check-*.log, all rc=0): `uv sync --locked
  --extra dev`; `ruff check .`; `ruff format --check` clean (3,652 files);
  maistro-evolve replay suites 11 passed; conductor subset 46 passed /
  19 skipped without DSN; suite-inventory gates ok (hive-conductor backend
  4540, maistro-evolve 1017).
- **PG acceptance legs re-run by this verifier with
  `MAISTRO_TEST_PG_DSN=postgresql://maistro:maistro@127.0.0.1:5570/maistro_test`
  (PG18 container `maistro-1064-pg`, alembic `069`): 65 passed, 0 skipped**
  (`test_evolution_restart_replay.py` + `_pg.py` + startup wiring + domain
  retention + domain store), including the distinct-OS-process recovery leg
  (`test_evolution_restart_replay_pg.py:486`), the per-boundary finalize fault
  parametrization, the concurrent-publisher fence legs
  (`test_evolve_domain_store.py:198,218`), and the fresh-cycle leg asserting a
  new NodeRun still publishes a new battle
  (`test_evolution_restart_replay.py:830-851`).
- `packages/maistro-evolve/tests/test_domain_reconstruction.py +
  test_durable_snapshot.py` — 11 passed.
- `tests/cross_product_parity/test_cross_product_parity.py::
  test_evolve_required_scenario_emits_strict_closeout_evidence` — 1 passed in
  1.19s at this head.
- **#947 P1 disposition re-checked live** (GraphQL reviewThreads): 7 threads,
  6 resolved; the only open thread is the P2 residual "Record the durable
  executor" — unchanged, outside this issue's P1-specific criterion.
- **Closure-keyword scan**: `git log a6a0969ca1..0389a4797f99` commit subjects
  and bodies contain no fixes/closes/resolves #N; live PR #2497 body
  (headRefOid == this exact SHA) contains only "Refs #1064".

Hosted exact-head CI this round (`gh pr view 2497`, 2026-11-23T23:33Z):

- Rollup at `0389a4797f99`: 81 checks — 71 COMPLETED with **0 failures**
  (2 SKIPPED by design: MinIO, durable-events), 9 IN_PROGRESS (`test`,
  coverage PostgreSQL / no-services, integration-scope, Container scan+SBOM,
  postgres pg18, hive-conductor e2e/e2e-ui, docker-build), 1 null context.
  The Coverage gate has not started (its producer jobs are still running), so
  the pending run cannot be called green either way.
- The prior head's settled reds stand at equal code content:
  quality run `45282026375` (Coverage gate — publish-set 83 < floor 87,
  branch-attributable) and CI run `45282026328` (`test` job, which carries the
  6 pre-existing "Event loop is closed" annotations also failing on
  develop@a6a0969ca1, plus one `test_builders_required_scenario_emits_strict_
  closeout_evidence` parity assert failure in-job).
- **Local exact reproduction of the hosted one-process step** at this head
  (`.github/workflows/ci.yml:747`: `uv run pytest tests/
  packages/hive-conductor/backend/tests packages/maistro-design/tests -q
  --timeout=60`, `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1
  RATCHET_BASE_REV=origin/develop`): 11,221 passed / 207 skipped / **1
  failed** — `tests/test_branch_independence_repository.py::
  test_every_quality_json_state_surface_is_classified_once` with
  `unclassified quality state: quality/ac-state.json`. That file is an
  **untracked, gitignored runtime artifact** (`.gitignore:88`, 619 KB written
  by a driver's check run in this shared worktree), not branch content: the
  same check against an artifact-free copy of `quality/` in a temp root
  returns `[]`, and re-adding the artifact reproduces exactly the observed
  violation. The hosted parity failure did not reproduce locally on identical
  test content under CI's exact command; it is recorded as hosted-run
  instability in a job that is already red on the develop base with the same
  event-loop flake family.

Verdict for this round: **NEEDS-REPAIR** — every locally executable acceptance
leg re-executed and passed at this exact SHA with real PostgreSQL; #947 P1
disposition met; no premature closure keywords. The single open criterion
remains close-only hosted exact-SHA CI: the last settled run at this code
content failed the branch-attributable coverage floor gate, the current head's
run is still in flight with that gate unstarted, and the repair recorded in
round 4 (covered arcs, floor grant under the two-merge process, or producer
scoping — a repair-lane decision) has not landed in any commit.
## Round 6 — assigned head `3c424c8afc55` revalidation (2026-11-23)

The assigned commit changes only this verification record relative to the
production/test source already checked at `0389a4797f99`. I independently ran:

- `MAISTRO_TEST_PG_DSN=postgresql://maistro:maistro@127.0.0.1:5570/maistro_test
  uv run pytest packages/hive-conductor/backend/tests/test_evolution_restart_replay.py
  packages/hive-conductor/backend/tests/test_evolution_restart_replay_pg.py
  packages/hive-conductor/backend/tests/test_evolution_startup_wiring.py
  packages/hive-conductor/backend/tests/test_evolve_domain_retention.py
  packages/hive-conductor/backend/tests/test_evolve_domain_store.py -x -q`
  -> **65 passed, 0 skipped**.
- `uv run pytest packages/maistro-evolve/tests/test_domain_reconstruction.py
  packages/maistro-evolve/tests/test_durable_snapshot.py -x -q` -> **11 passed**.
- Strict cross-product scenario selector -> **1 passed**.
- `uv run ruff check . && uv run ruff format --check .` -> passed; 3,652 files
  formatted. Suite-inventory gates: hive-conductor backend **4540** and
  maistro-evolve **1017**, both matched.
- Live `gh pr view 2497` reports PR head `0389a4797f998bb768344819998370c22b5aac3d`
  (the exact production/test content) with completed check
  `Coverage gate (publish-set floor + diff coverage)` FAILURE. Thus current
  content does not meet exact-head CI acceptance. The #1064 acceptance
  criterion requiring exact-SHA CI is **UNVERIFIED/blocked by this failure**;
  no floor or gate was weakened here.

Verdict: **NEEDS-REPAIR**. The restart/replay behavioral legs pass locally,
but the measured hosted coverage gate is red and must be repaired on the
branch before this can be handed off as merge-ready.

## Round 7 — assigned head `1e94d9d45ed2` independent re-verification (2026-11-24)

The assigned head equals the live PR #2497 `headRefOid` (fresh `gh pr view`
reading) and is one docs commit past the code-validated head `3c424c8afc55`;
`git diff --stat 0389a4797f99..1e94d9d45ed2` touches only this note (+105),
so all production/test content is identical to what the round-4/5/6 legs
validated. All locally executable legs were re-executed by this verifier at
the exact assigned head (worktree clean at `1e94d9d45ed2`, PG18 container
`maistro-1064-pg`, DSN `postgresql://maistro:maistro@127.0.0.1:5570/maistro_test`,
alembic `069`):

- Replay/fencing/startup/retention/store legs (`test_evolution_restart_replay.py`,
  `_pg.py`, `test_evolution_startup_wiring.py`, `test_evolve_domain_retention.py`,
  `test_evolve_domain_store.py`) -> **65 passed, 0 skipped in 39.95s**, including
  the distinct-OS-process recovery leg, per-boundary finalize fault
  parametrization, concurrent-publisher fences, and the fresh-cycle
  non-suppression leg.
- `packages/maistro-evolve/tests/test_domain_reconstruction.py +
  test_durable_snapshot.py` -> **11 passed**.
- `tests/cross_product_parity/…::test_evolve_required_scenario_emits_strict_closeout_evidence`
  -> **1 passed in 1.22s**.
- `uv run ruff check .` -> passed; `uv run ruff format --check .` -> clean
  (3,652 files). `uv run python scripts/check-suite-inventory.py` (CI's exact
  command, ci.yml:751) -> **ok: 21 suite(s) match the recorded inventory**;
  driver deterministic checks (job check-*.log) additionally recorded
  hive-conductor backend 4540 and maistro-evolve 1017 suite matches.
- Closure-keyword scan `git log a6a0969ca1..1e94d9d45ed2 --format='%B'` ->
  no fixes/closes/resolves #N (42 commits); live PR body still only "Refs #1064".
- Live rollup at the exact head (run started 2026-11-24T00:03:44Z): **57
  COMPLETED/SUCCESS, 2 SKIPPED, 1 NEUTRAL (CodeQL), 19 IN_PROGRESS, 0
  failures**, `gates-ran` PENDING, and the
  `Coverage gate (publish-set floor + diff coverage)` check has **not yet
  started** (its producer jobs `coverage (no services|MinIO|PostgreSQL)` are
  IN_PROGRESS). Pending is not green; the criterion stays unsettled.

The last **settled** hosted run at content-identical code (round-4 addendum,
job `138078750667`, run `45282026375`) failed
`Coverage gate (publish-set floor + diff coverage)` with publish-set coverage
83 < floor 87, branch-attributable against a green develop base run
`45239478051` at the merge base; no floor grant, producer scoping, or covered-arc
repair has landed in any commit since. Nothing in this round weakened a gate.

Verdict: **NEEDS-REPAIR** — every locally executable acceptance criterion is
proven at this exact SHA by this verifier's own runs with real PostgreSQL and
the #947 P1 disposition remains met, but the close-only exact-SHA/CI criterion
is unmet: settled branch-attributable coverage-gate FAILURE at identical
content, current head's run still in flight with that gate unstarted.

## Assigned repair-worker revalidation at `57201708d320` (2026-11-24)

The assigned worktree was clean at the stated starting head; no `check-*.log`
files were present in this job directory. Re-executed local acceptance checks:

- `MAISTRO_TEST_PG_DSN=postgresql://maistro:maistro@127.0.0.1:5570/maistro_test
  uv run pytest packages/hive-conductor/backend/tests/test_evolution_restart_replay.py
  packages/hive-conductor/backend/tests/test_evolution_restart_replay_pg.py
  -x -q` -> **38 passed** (real PostgreSQL; includes restart/replay and
  process-boundary legs).
- `uv run pytest
  tests/cross_product_parity/test_cross_product_parity.py::test_evolve_required_scenario_emits_strict_closeout_evidence
  -x -q` -> **1 passed**.
- `uv run ruff check .` and `uv run ruff format --check .` -> passed; format
  check reports 3,652 files already formatted.
- `uv run python scripts/check-suite-inventory.py` -> **21 suites match**,
  including hive-conductor backend 4,540 and maistro-evolve 1,017 node IDs.
- `git diff --check` -> clean before this evidence-only note update.

No production or test change was justified by these passing local checks. The
actual outstanding repair evidence is the content-identical hosted run
`45282026375` / job `138078750667` failing publish-set coverage at 83 against
floor 87 (develop base run `45239478051` was green), as captured above and in
the supplied prior findings. The exact-head current rollup was still pending
with coverage not started per the supplied evidence; this worker did not claim
that pending status as green. No coverage floor/producer gate was weakened.

Verdict remains **NEEDS-REPAIR**: local replay acceptance is re-proven, but
exact-head hosted CI is not green and the known coverage failure remains
unrepaired. The supplied #947 disposition satisfies the recorded P1-specific
criterion; its unresolved P2 thread remains outside that criterion.

## Round 8 — assigned head `a976b0ad48d4` verifier+writer round (2026-11-24)

Prior-block resolution: the previous worker round had committed the
`57201708d320` revalidation section above; this round treats that commit as
the handed-off baseline (not as proof of repair) and re-derives everything
itself. Driver deterministic checks in this job directory (`check-0..6.log`,
all rc=0): `uv sync --locked --extra dev`; `ruff check .`; `ruff format
--check .` clean (3,652 files); maistro-evolve replay suites 11 passed;
conductor subset 46 passed / 19 skipped without DSN; suite-inventory gates ok
(hive-conductor backend 4,540 node IDs; maistro-evolve 1,017).

Content chain re-proven, not inherited: `git diff --numstat
31c38337db1d..a976b0ad48d4` = this note only (+273 docs lines across the
intervening verification commits) — no `.github/`, `quality/`, or
`packages/` change since the coverage-gate-failing head `31c38337db1d`
(branch numstat vs develop base shows `.github/workflows/quality.yml` +23 and
`quality/durable-table-retention.json` +26 only; no coverage-floor grant or
producer scoping landed). The settled RED therefore still applies to
identical code content: hosted run `45282026375` / job `138078750667`,
`Coverage gate (publish-set floor + diff coverage)` — publish-set 83 <
floor 87, branch-attributable against a green develop-base run
`45239478051`.

Re-executed by this verifier at the exact assigned head (PG18 container
`maistro-1064-pg`, `MAISTRO_TEST_PG_DSN=…127.0.0.1:5570/maistro_test`):

- Six conductor suites (restart/replay + `_pg.py` + startup wiring + domain
  retention + durable store + recovery) -> **79 passed, 0 skipped in 37.7s**,
  including the distinct-OS-process recovery leg, the per-boundary finalize
  fault parametrization, concurrent-publisher fences, and the fresh-cycle
  non-suppression leg.
- `packages/maistro-evolve/tests/test_domain_reconstruction.py +
  test_durable_snapshot.py` -> **11 passed**.
- `tests/cross_product_parity/…::test_evolve_required_scenario_emits_strict_
  closeout_evidence` -> **1 passed in 1.26s**.

Live read-only refreshes this round:

- `gh pr view 2497`: headRefOid == `a976b0ad48d4` (exact head). Rollup (run
  `45302431044`, started 2026-11-24T01:06Z): **64 SUCCESS / 2 SKIPPED / 13
  IN_PROGRESS / 1 null / 0 failures**; `coverage (no services)` and
  `coverage (PostgreSQL)` still IN_PROGRESS, so the
  `Coverage gate (publish-set floor + diff coverage)` has **not started**.
  Pending is not green: the exact-SHA/CI criterion is UNVERIFIED at this
  head while the content-identical settled evidence is RED.
- `#947` review threads re-checked live via GraphQL: 7 threads; **4/4 P1
  resolved** (`PRRT_…dTA`, `…dTF`, `…dTK`, `…dTR`); the only open thread is
  the P2 residual `PRRT_kwDOT-he_M6d9dTY` ("Record the durable executor"),
  unchanged and outside this issue's P1-specific disposition criterion.
- Closure-keyword scan: `git log a6a0969ca1..a976b0ad48d4 | grep -Ei
  '(fix(es|ed)?|closes?|resolves?) #[0-9]+'` -> no matches; live PR body
  contains only "Refs #1064".

Verdict remains **NEEDS-REPAIR**: every locally executable acceptance leg
passes at this exact SHA with real PostgreSQL and the #947 P1 disposition is
met, but the close-only exact-SHA/CI criterion is unmet — the settled
branch-attributable coverage-gate FAILURE at identical content is the
concrete repair still owed (covered arcs for the new backend-service code, a
floor grant under the two-merge authorization process, or producer-set
scoping — a repair-lane decision), and the current head's hosted run had not
settled its coverage gate at capture time. Nothing in this round weakened a
gate, edited production code, or claimed pending CI as green. The stale
round-7 rollup counts above (57/19) are retained as a time-stamped record;
this section supersedes them with fresh readings.

## Round 9 — exact PR head `02a957bd0823` verifier+writer round (2026-11-24T01:14–01:55Z)

Independent re-verification at the exact assigned/PR head, all evidence
first-hand this round. Verification ran entirely at `02a957bd0823` before any
writer edit; the docs-only commit below was made after evidence capture.

Locally executed at this head (PG18 container `maistro-1064-pg`,
`MAISTRO_TEST_PG_DSN=…127.0.0.1:5570/maistro_test`, `MAISTRO_REQUIRE_PG_LEGS=1`
so a skip fails loudly):

- CI-producer suite list (`test_evolution_restart_replay.py`,
  `test_evolution_restart_replay_pg.py`, `test_evolve_domain_retention.py`,
  `test_evolve_domain_store.py`, `--timeout=120 -q`) -> **52 passed, 0
  skipped** (twice: once for pass/fail, once under
  `coverage run --branch --source=packages/hive-conductor/backend/services`).
- `test_evolution_startup_wiring.py` + `test_evolution_recovery.py` ->
  **27 passed**. Six-suite total 52+27 = **79, matching Round 8's record**.
- `tests/cross_product_parity` with CI's exact invocation -> **26 passed**.
- maistro-evolve unit producer under coverage (`--source=…/maistro_evolve`)
  -> **1005 passed, 12 skipped** (= recorded inventory 1017).
- Floor-poisoning mechanism, measured: the branch's
  `coverage-postgres` producer step scopes
  `--source=packages/hive-conductor/backend/services` into the artifact that
  `coverage-gate` combines **before** the 87% floor. That source alone is
  **15,542 statements at 11% (13,531 missed), 79 modules at 0%**. Combining
  it with the evolve-unit producer and running CI's own
  `coverage report --fail-under=87` -> **exit 2** (TOTAL 21,245 stmts @ 33%).
  The mechanism is deterministic: no publish-set base can absorb it.

Hosted, read-only, first-hand this round:

- `gh pr view 2497`: headRefOid == `02a957bd0823…` (exact). Rollup run
  `45303482226` (started 2026-11-24T01:14Z; run still in progress at final
  capture).
- **Exact-head coverage gate settled RED, first-hand**: check-run
  "Coverage gate (publish-set floor + diff coverage)" id `138149529335`
  -> completed/**failure**; its `combine` step logged
  `TOTAL 110859 17046 29740 1913 83%`, `Coverage failure: total of 83 is
  less than fail-under=87`, `##[error]publish-set coverage below the 87%
  floor` — byte-identical numbers to the 31c38337db run `45282026375`
  (content identical; determinism confirmed across two runs).
- **Exact-head `cross-product-parity` settled FAILURE (ci.yml, new this
  round)**: job `138141739495`, step "Cross-product spine parity suite
  (#459, development mode)" exit 1 —
  `test_builders_required_scenario_emits_strict_closeout_evidence FAILED`
  with `sqlite3.ProgrammingError: Cannot operate on a closed database.`
  (packages/maistro-core/src/maistro/builders/interactive.py:162),
  `RuntimeError: no running event loop`, `ValueError: no legal transition
  path from 'cancelled' to 'running'`, and a `…'completed': False` vs
  `True` response mismatch. Passes locally at the same SHA and passed
  hosted at the content-identical predecessor `57201708d3` (run
  `45295830614` success), so this is timing-sensitive async shutdown
  exposure, not a code regression from the docs-only delta — but it is a
  settled required-check FAILURE at the exact head.
- Branch-attributability re-verified: quality run `45239478051` at develop
  base `a6a0969ca1…` -> **success** (same workflow).
- `#947` re-checked live (GraphQL, all 7 threads): **4/4 P1 resolved**
  (`…dTA`, `…dTF`, `…dTK`, `…dTR`); P2 `…dTY` ("Record the durable
  executor") open, plus two resolved P2s — P1-specific criterion met.
- Closure keywords: none (branch `git log a6a0969ca1..02a957bd0823` — no
  `fixes/closes/resolves #N`; PR body says only "Refs #1064").

Verdict: **NEEDS-REPAIR** (unchanged, now fully settled at the exact head).
Every locally executable acceptance leg passes with real PostgreSQL, but
"exact SHA/CI" is unmet twice over at `02a957bd0823`: (1) the coverage gate
is deterministically RED (publish-set 83 < 87) — the branch's own producer
poisons the pre-floor combine with a 15,542-statement source at 11%, so the
repair must either scope that producer out of the pre-floor artifact
(post-floor combine or diff-gate-only producer) or bring the source's
covered area above the floor's arithmetic, via the two-merge floor-raise
process if a grant is the chosen path; (2) `cross-product-parity` is RED at
this head on a timing-sensitive builders leg (closed-database /
event-loop shutdown race) that CI must see green at the exact SHA. Prior
rounds' "coverage gate unsettled" caveat is hereby closed: the gate has
settled RED twice at identical content, the second time at this exact SHA.

## Round 10 — exact-head `1c3e01c65b` re-verification (2026-11-24, this round)

Context: the round-9 job's verification was administratively rejected because its
writer commit (`1c3e01c65b`, docs-only) landed mid-run and changed the worktree
under the evidence; the repair demand "clean tree is not proof of repair" is
resolved here by (a) re-deriving every acceptance leg at the frozen head and
(b) landing this docs-only evidence commit *after* the runs below finished.
No code, gate, or quality-ledger file was touched this round.

Local, executed this round at exact head `1c3e01c65bf9bdb52334ee6a7c395a6d780d5d18`
(real PostgreSQL at `127.0.0.1:5570`, `MAISTRO_TEST_PG_DSN` +
`MAISTRO_REQUIRE_PG_LEGS=1` so skips fail):

- Driver pre-checks at this head, all green: `uv sync --locked --extra dev`,
  `ruff check .`, `ruff format --check .` (3652 files), evolve suites
  `test_domain_reconstruction.py` + `test_durable_snapshot.py` (11 passed),
  five hive-conductor suites without DSN (46 passed, 19 skipped),
  `check-suite-inventory.py` for `packages/hive-conductor/backend/tests`
  (4540) and `packages/maistro-evolve/tests` (1017).
- Five hive-conductor suites with real PG + REQUIRE flag: **65 passed,
  0 skipped** (replay fault-injection incl. distinct-process legs, startup
  wiring, retention, domain store/fences).
- `tests/cross_product_parity` with CI's exact invocation (ci.yml:952):
  **26 passed** — the hosted failure at `02a957bd0823` remains
  timing-sensitive, not a local reproducible regression.
- Coverage producers reproduced at this head: maistro-evolve producer
  **1005 passed + 12 skipped = 1017** (inventory match); hive-conductor
  evolve producer with CI's exact 4-file invocation: **52 passed** under
  real PG.
- Floor mechanism re-measured at this head: scoped
  `--include=packages/hive-conductor/backend/services` on the combined
  producer DB = **15,542 stmts @ 11% (13,531 missed), 79 modules at 0%**;
  CI's own `coverage report --fail-under=87` on that DB -> **exit 2**
  (`Coverage failure: total of 33 is less than fail-under=87` on the
  two-producer subset; hosted full combine measures 83). Deterministic.

Hosted, read-only, first-hand this round:

- `gh pr view 2497`: headRefOid == `1c3e01c65bf9…` (exact, draft, OPEN).
  Rollup at final capture: **65 SUCCESS / 2 SKIPPED / 13 IN_PROGRESS /
  1 PENDING**; zero settled failures so far at this head, but
  `coverage (no services)`, `coverage (PostgreSQL)`, `test`,
  `integration-scope`, `Quality / Acceptance state` and the Coverage gate
  consumer itself had not settled — pending is not green.
- Content identity re-verified via numstat: `57201708d3 -> 02a957bd0823 ->
  1c3e01c65bf9` are each docs-only (this file only). Therefore the settled
  REDs at `02a957bd0823` (coverage gate 83 < 87, check-run 138149529335;
  cross-product-parity job 138141739495) apply deterministically to this
  head's code content.
- Branch-attributability stands: develop-base quality run `45239478051`
  (same workflow) is success.
- Closure keywords: none (`git log a6a0969ca1..1c3e01c65bf9` grep clean;
  PR body "Refs #1064" only).

Verdict: **NEEDS-REPAIR** (unchanged). The repair owed is unchanged from
round 9: scope the hive-conductor `backend/services` producer out of the
pre-floor publish-set combine (post-floor combine or diff-gate-only) or
raise the floor through the two-merge grant process — and the
timing-sensitive `cross-product-parity` builders leg must settle green at
the exact SHA. Local replay-safety acceptance (all fault-injection PG legs,
parity, fences, diagnostics) is green at this exact head; only the CI
criterion blocks.

## Round 11 — repair of measured coverage classification (2026-11-24)

The round-10 coverage diagnosis was actionable: `coverage-postgres` included
`packages/hive-conductor/backend/services` in the pre-floor aggregate although
that code is outside the publish set. Updated `.github/workflows/quality.yml`
to retain this producer's artifact until after the unchanged 87% publish-set
floor, then combine it before the diff-coverage producers. This preserves
changed-line coverage measurement for Hive Conductor; it does not omit the
code from `coverage.xml`, lower a floor, or alter measured roots. The explicit
missing-artifact check remains in place.

Executed after the workflow change: `uv run ruff check .` and `uv run ruff
format --check .` passed; `uv run pytest tests/test_check_diff_coverage.py -q
-x` passed (18); the five Evolve backend suites passed 46 with 19 PG-dependent
cases skipped because no `MAISTRO_TEST_PG_DSN` was configured. Thus these
current runs do not re-prove PG recovery. The production implementation is
unchanged from round 10's real-PostgreSQL evidence, but the coverage workflow
change has not yet been exercised by hosted CI and the timing-sensitive
cross-product-parity check still requires exact-head settlement. Verdict:
**NEEDS-REPAIR** pending exact-head CI evidence; no new tests or inventory
counts were added.

## Round 12 — independent verifier re-execution at exact head `1bd985be0a` (2026-11-24)

Re-derived and re-executed at this exact worktree head; nothing inherited from
prior summaries. Worktree confirmed clean at `1bd985be0a` for the entire run;
no state-changing git operations were used.

Executed by the verifier against PostgreSQL 18 (`maistro-1064-pg`, migrated,
82 public tables):

- `uv run ruff check .` — pass.
- Restart/replay legs `test_evolution_restart_replay.py` +
  `test_evolution_restart_replay_pg.py` with `MAISTRO_TEST_PG_DSN`:
  **38 passed, 0 skipped** (evaluation receipts, committed-finalize evidence,
  hard-kill mid-finalize, and the distinct-OS-subprocess recovery leg).
- `test_evolution_startup_wiring.py` + `test_evolve_domain_retention.py` +
  `test_evolve_domain_store.py` with the DSN: **27 passed** → **65 total
  Evolve PG legs, 0 skipped**, matching the round-10 claim, now re-executed.
- Evolve units `test_domain_reconstruction.py` + `test_durable_snapshot.py`:
  **11 passed**.
- `tests/cross_product_parity` with CI's exact invocation (ci.yml:952,
  `REQUIRE_AUTH=false`, `MAISTRO_DRY_RUN=1`): **26 passed**.
- `tests/test_check_diff_coverage.py`: **18 passed** (MEASURED_ROOTS includes
  `packages/hive-conductor/backend/services`; agreement with the producer
  `--source` asserted).

Live hosted evidence (read-only `gh pr view 2497` refresh at this head):
`headRefOid` is `1bd985be0a…`, draft; rollup **70 SUCCESS / 2 SKIPPED /
8 IN_PROGRESS / 1 null** — both coverage producers (`coverage (no services)`,
`coverage (PostgreSQL)`), `test`, `postgres (pg17)` and `hive-conductor-e2e`
still IN_PROGRESS; the publish-set coverage gate is downstream of the
producers and has not started. Per the standing rule, pending CI stays
UNVERIFIED and the exact-SHA/CI criterion is not settled at this head.

Workflow repair re-read at this head: `coverage-postgres` is excluded from the
pre-floor combine, the unchanged 87% publish-set floor is evaluated first, the
producer artifact is then appended for the diff gate with a hard error if it
contributed no data — no floor lowered, no measured code dropped. Closure
keywords: none in the branch commit messages or PR body ("Refs" only). The
#947 thread disposition remains a #51 closeout item (P2 thread, outside this
issue's P1-specific criterion), unchanged from round 11.

This docs-only record shifts the PR head; hosted exact-head CI must settle at
the new head before the CI criterion is proven. Verdict: **NEEDS-REPAIR**,
solely pending hosted exact-head settlement.

## Round 13 — independent verifier re-execution at exact head `5a9b0d2d` (2026-11-24)

Re-derived from the issue text, not inherited. Worktree confirmed clean at
`5a9b0d2d` at start; the only tree mutations this round are the evidence-driven
digest repair recorded below, applied as the dispatch writer after the hosted
failure was reproduced locally.

Re-executed against PostgreSQL 18 (`maistro-1064-pg`, migrated, revision 069):

- Restart/replay + startup-wiring + retention + domain-store suites with
  `MAISTRO_TEST_PG_DSN`: **65 passed, 0 skipped** (38 restart/replay incl. the
  distinct-OS-subprocess leg; the driver's own run had left 19 PG cases
  skipped without a DSN — those are now executed, not trusted).
- Migration chain against a scratch PG database (`maistro_migration_scratch`,
  dropped afterwards): **18 passed** — the fixture-destructive legs the driver
  skipped now run on real PostgreSQL through revision 069.
- Evolve units: **11 passed**. Parity with CI's exact env (ci.yml:952): **26
  passed**. Diff-coverage agreement: **18 passed**. `ruff check .` and
  `ruff format --check .`: pass. Suite-inventory gates: pass (4540 + 1017,
  0 duplicates — driver logs check-5/check-6).

Hosted settlement at `5a9b0d2d` (live `gh pr view 2497` polls, head verified
each time): the run drained from 21 → 10 → 5 → 1 IN_PROGRESS with 0 failures
until the `test` job (id 138180853002, run 45315246527) completed **failure**:
5965 passed, 1 failed —
`tests/test_ci_quality_split.py::test_every_original_quality_obligation_survives_with_its_profile`,
`AssertionError: '7998ee9e...' == '7211a89d...'`.

**Defect reproduced locally in 0.76 s at the exact head, and attributed.** The
repair commit `1bd985be` rewrote the `coverage-gate` job in
`.github/workflows/quality.yml` (hold `coverage-postgres` out of the pre-floor
combine) but did not refresh the SHA-256 job digest pinned in
`tests/fixtures/ci_quality_obligations.json`. The fixture's `coverage-postgres`
line had been updated; the `coverage-gate` line was not. Digest recomputation:
base workflow coverage-gate == base fixture pin (`7211a89d…`, self-consistent —
develop is green); head workflow coverage-gate digests to `7998ee9e…`. Sole
consumer is `tests/test_ci_quality_split.py` itself, so the pin is a truthful
anti-tamper ratchet over CI obligations, not a policy floor.

**Writer repair applied:** one line in `tests/fixtures/ci_quality_obligations.json`
— `coverage-gate` pin `7211a89d…` → `7998ee9e…` (the digest of the reviewed
workflow repair, recomputed with the test's own `_digest`). No workflow, gate,
or floor change. `uv run pytest tests/test_ci_quality_split.py -q`:
**96 passed**. No closure keywords introduced.

The #947 review threads were re-read live this round: all four P1 threads carry
explicit dispositions (battle replay → #1064 fix; finalize replay → #1064 fix;
restart resolver → #1064 fix; embedded-core preservation → #1066, closed by
#1300/#1299). The single undisposed thread is the P2 "Record the durable
executor on admitted Evolve runs" — outside this issue's P1-specific
criterion, carried to the #51 closeout as recorded in rounds 11-12.

The commit that carries this record moves the PR head again; hosted CI restarts
at the new head and must settle there before the exact-SHA/CI criterion is
proven. Verdict: **NEEDS-REPAIR** — the deterministic digest defect is repaired
and locally proven; sole remaining item is hosted exact-head settlement.

Round-13 postscript — full hosted settlement at `5a9b0d2d`. After the `test`
job failure recorded above, the remaining producer finished SUCCESS
(`coverage (no services)`) and the "Coverage gate (publish-set floor + diff
coverage)" job then ran and also failed: **1 failed, 6080 passed, 140
skipped** (job 138188150839, run 45315246228) — the identical
`test_ci_quality_split.py` digest assertion, `- 7211a89d…` vs `+ 7998ee9e…`.
Both hosted failures therefore trace to the single stale digest pin repaired
above; no second defect is evidenced, and every other check at that head
settled SUCCESS (incl. `postgres (pg17)`, `postgres (pg18)`, both e2e suites
and all three coverage producers). The publish-set floor itself was not
evaluated in that run (pytest exits before the combine step), so the floor
verdict remains pending at the repair head `9e50b3fcf1`.

## Round 14 — independent exact-head recheck at `b6675803` (2026-11-24)

Started clean at the assigned head `b66758034b65b497d76b484d37025dc02027c765`,
which contains the digest repair (`9e50b3fcf1`) and its hosted-settlement
record. No production/test defect was found or guessed at; no test or code
changes were made.

Local commands executed:

- `uv run ruff check . && uv run ruff format --check .` — passed (3,652
  files formatted).
- `uv run pytest packages/maistro-evolve/tests/test_domain_reconstruction.py
  packages/maistro-evolve/tests/test_durable_snapshot.py -x -q` — **11 passed**.
- `uv run pytest packages/hive-conductor/backend/tests/test_evolution_restart_replay.py
  packages/hive-conductor/backend/tests/test_evolution_restart_replay_pg.py
  packages/hive-conductor/backend/tests/test_evolution_startup_wiring.py
  packages/hive-conductor/backend/tests/test_evolve_domain_retention.py
  packages/hive-conductor/backend/tests/test_evolve_domain_store.py -x -q` —
  **46 passed, 19 skipped**. Neither `MAISTRO_TEST_PG_DSN` nor `DATABASE_URL`
  is configured in this runner; skipped PostgreSQL legs are not local
  evidence. The previously recorded real-PG run is not re-claimed as freshly
  executed here.

Live `gh pr checks 2497` confirmed the exact head remains
`b66758034b65b497d76b484d37025dc02027c765`; the digest check and coverage
producers are green, but required `test` and `Coverage gate (publish-set floor
+ diff coverage)` remain **pending**, as does `gates-ran`. Thus the repaired
red check is no longer observed, but the publish-set floor is not proven green
at the assigned SHA. No GitHub mutations made.

Verdict: **NEEDS-REPAIR** solely because exact-SHA hosted settlement is still
pending. No local tree defect is evidenced. This verification note itself
will advance the head; hosted checks must settle again at the resulting commit
before claiming merge readiness.

## Round: deep-review r2 — hosted settlement observed RED; root cause found and repaired locally

Observed at the exact assigned head `b0b32ec9874b62cba60f8583e94c55074c2aff89`
(PR #2497 head confirmed via `gh pr view` this round): after ~28 minutes the
pending `Coverage gate (publish-set floor + diff coverage)` check settled
**FAILURE** (completed 2026-11-24T05:12:21Z). Every other check at this head is
SUCCESS (79 of 80 completed checks; `gates-ran` flips only after). The prior
rounds' "pending, never inferred green" discipline was correct: it settled red.

Failing step: `Diff coverage gate (per file, lines 90% / branches 80%)`, five
files:

- `services/evolution.py` 89.6% of 125 changed lines — uncovered 380-388,
  391, 394, 395 (the entire `refresh_committed_finalize_evidence` body: the
  durable committed-finalize evidence the recovery resolver consults) and 607
  (the culled-genome receipt skip in evaluation journal replay);
- `services/evolve_domain_store.py` 72.7% of 22 changed branch arcs — partial
  at 258 (evaluation exactly-once fence, loser outcome), 374/416/500 (PG
  snapshot/battle/evaluation lookup misses);
- `maistro_evolve/durable_snapshot.py`, `population.py`, `tournament.py` —
  "absent from the coverage report — the measurement did not happen".

### Root cause of the three "absent" files (reproduced end-to-end locally)

`coverage combine` **replaces** its destination with the merge of the current
`.coverage.*` files. The gate combines unit+archive first, then moves
`coverage-postgres` in and combines **again** — the second combine silently
discards the first combine's database (the one the 87% floor just evaluated).
The real gate log proves it: the post-floor report (04:45:08Z) prints
`population.py` 97% / `tournament.py` 99% / `durable_snapshot.py` 100%, while
the final coverage.xml (05:12Z) has no entry for them. The trio is measured
only by the unit producer, and the postgres artifact holds zero
`maistro-evolve` entries, so nothing re-measures them after the wipe. Local
replay with the run's actual artifacts reproduced exactly this: unit+archive
combined keeps 58 evolve entries; moving postgres in and re-combining leaves 0.

### Repair (committed on this branch; hosted CI must settle at the new head)

1. `.github/workflows/quality.yml`: the second combine is now
   `coverage combine --append` — append the postgres producer into the floor's
   database instead of replacing it. Validated against the run's real
   downloaded artifacts: the repaired combine keeps 58 evolve + 118
   hive-conductor-service entries in one database (1114 files), and the actual
   `scripts/check-diff-coverage.py` run against the repaired xml shows the
   trio **passing** their per-file floors on the producer's own data
   (population.py +31 changed lines, tournament.py +130, durable_snapshot.py
   +20 all ≥90%/80% — no new tests needed for them).
2. `test_evolution_restart_replay.py`: the three refresh outcomes (no store;
   store without the ledger method → conservative refusal; real ledger →
   committed markers admitted, faulted excluded — the ledger's answer replaces
   seeded evidence, it is the authority) plus the culled-genome replay skip.
   These cover every hosted-uncovered `evolution.py` line.
3. `test_evolve_domain_store.py`: the evaluation-publication exactly-once
   fence (loser outcome) across memory/sqlite, and the three PG lookup miss
   outcomes (fresh workspace answers None for snapshot, battle receipt,
   evaluation receipt).
4. Fixture digest for the edited `coverage-gate` job repinned in
   `tests/fixtures/ci_quality_obligations.json`
   (7998ee9e… → 01a08e42…); `tests/test_ci_quality_split.py` 96 passed.

Local validation at this head: 41 restart-replay/restart-replay-pg tests with a
real PG server (65 total across the five recovery suites incl. the
distinct-OS-process subprocess leg), 15/12 store-suite tests with and without
DSN, 96 fixture tests, ruff + format clean, suite inventory +6 recorded in
`1064-verification-repair-round2.md` (4546 unique identities, 0 duplicates),
evolve suite unchanged at 1017. `scripts/run-m1-closeout.py` evidence line
re-captured live this round: `evolve-cycle-to-conductor … "executed": true,
"status": "PASSED", "blockers": []`; scheduler-occurrence (#231) and
golden-real-observation (#463) abstain exactly as at the develop base
(pre-existing, unrelated). PR #947 review threads re-read live: all three P1s
RESOLVED; sole open thread is the P2 "Record the durable executor on admitted
Evolve runs" advisory.

Verdict: the tree defect the hosted red exposed is repaired locally; the
exact-SHA settlement criterion reopens at the resulting commit and must settle
green there before merge readiness. No GitHub mutations made.

## Round: 2026-11-24 — exact-SHA hosted settlement at c467355f1c9c

Head under test: `c467355f1c9ce484619441f726d0b8399040eaaa` (= live PR #2497
head at capture time). This round ran checks only; it changed no code and made
no push, so the settlement below remains attached to the PR head.

Hosted settlement, read live via the commit check-runs API for the exact SHA:

- `gh api repos/.../commits/c467355f1c.../check-runs` -> conclusion multiset
  `{success: 79, skipped: 2}`; the filter for any other conclusion returned an
  empty list. `skipped` = `durable-events`, `object storage (MinIO)`
  (service-gated, same two as every earlier observation).
- `Coverage gate (publish-set floor + diff coverage)` — **SUCCESS**. This is
  the gate that had never settled green at any prior head; the c467355f1c
  repair (`coverage combine --append`) settled it.
- `test` — SUCCESS; `gates-ran` — SUCCESS ("All required checks executed on
  this exact head"); `cross-product-parity`, `postgres (pg17)`,
  `postgres (pg18)`, `exact-debt-ledger`, `Mutation gate`, `Quality gate
  (Pillars 1–4, 7, 8)`, `Quality / Mypy strict`, `Quality / Pyright`,
  `Quality / Ruff`, `Quality / Vulture` — all SUCCESS.

Local re-execution at this head (independent of the hosted run):

- `MAISTRO_TEST_PG_DSN=postgresql://maistro:maistro@127.0.0.1:5570/maistro_test`
  (migrated pg18, `alembic_version` = `069`): restart-replay + restart-replay-pg
  + evolve-domain-store + evolve-domain-retention + startup-wiring +
  maistro-evolve durable-snapshot/domain-reconstruction -> **82 passed, 0
  skipped**; `test_pg_distinct_os_process_recovers_killed_run` re-run isolated
  -> 1 passed.
- `tests/test_ci_quality_split.py` -> 96 passed (fixture digests match live
  quality.yml incl. the repinned coverage-gate obligation 01a08e42…).
- `uv run ruff check .` / `uv run ruff format --check .` -> clean.
- `scripts/check-suite-inventory.py` -> 21 suites match the recorded
  inventory; 36443 collected node IDs, 0 duplicate identities.
- `scripts/run-m1-closeout.py` -> `evolve-cycle-to-conductor … "executed":
  true, "status": "PASSED", "blockers": []`; scheduler-occurrence (#231) and
  golden-real-observation (#463) abstain as not-shipped, pre-existing and
  unrelated to #1064.
- `git diff --numstat a6a0969ca198..HEAD -- quality/` -> only
  `quality/durable-table-retention.json` +26/−0; no ledger rows lost, no grant
  edits.
- PR #947 review threads re-read live (GraphQL): 7 threads, 6 RESOLVED
  (incl. all P1s); sole open thread is the P2 "Record the durable executor on
  admitted Evolve runs" advisory, outside the P1-specific disposition
  criterion.
- Closure-keyword scan across all 20 branch commit subjects/bodies -> none;
  no premature GitHub closure risk.

Verdict: every #1064 acceptance criterion now has executed evidence at the
exact PR head — hosted settlement is no longer open. No GitHub mutations made;
nothing pushed.
