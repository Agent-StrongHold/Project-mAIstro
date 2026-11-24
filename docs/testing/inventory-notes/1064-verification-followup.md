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

