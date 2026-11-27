# verify-37-0a6768d

Independent verification record for lane L37 (#37 — M1-A1 canonical
Workspace/Membership ownership and persistence) at head
`0a6768d2ce80c1e2c032f848464e9fdd00119c8c` (develop base
`4f8f40352d13281f217522a351ce47f99a1d1df6`). Supersedes the round at
`585cd8d2` (note `verify-37-585cd8d.md`) and the repair round at
`40f961d1ef`: the head moved by merging develop into the repaired branch,
so every claim below was re-executed at the merged head. No test counts
move beyond what develop itself added — this note records executed
evidence only.

## What the merge adds over the verified repair

`git diff 40f961d1ef..0a6768d2ce --name-only` touches none of the #37
production fence or repair files (`projects/scope_store.py`,
`projects/pg_scope_store.py`, `workspaces/pg_store.py`,
`tasks/admission.py`, `alembic/versions/071_*.py`,
`personas/test_durable_store_pg.py`, `tests/migrations/`). It adds
CHANGELOG/ADR-880 material, maistro-turing runtime/tests, and one new
formal model, `formal/models/test_execution_lifecycle.py` — a pure
in-memory machine over `maistro.runs.lifecycle.transition_run` with no
database and no Workspace provisioning, so it cannot interact with the
#37 admission fence; confirmed by the suite run below. Quality ledgers
are untouched by the merge (`git diff 40f961d1ef..HEAD -- quality/` is
empty), so no rows were lost resolving the merge.

## Executed at this head

Environment: `pgvector/pgvector:pg18` (the formal-conformance.yml image)
at `127.0.0.1:5435`; fresh databases `maistro_test` (migrated) and
`maistro_mig` (created for this round, unmigrated, CI-shaped);
`MAISTRO_REQUIRE_PG_LEGS=1`; `uv sync --locked --extra dev` venv plus the
CI-mandated `-e formal/` and `-e packages/maistro-evolve` installs (the
uv workspace does not carry `maistro_evolve`; both RSI conformance
modules error on collection without it, matching the workflow comment).

Named gate formal-conformance.yml, CI's exact arguments:

- Step `Apply migrations` (DATABASE_URL scoped to the step): chain
  applies cleanly to revision **071 (head)** on the fresh database.
- Step `Run formal models` — `pytest formal/models/ --timeout=300
  --hypothesis-seed=0` with `MAISTRO_TEST_PG_DSN`/`MAISTRO_TEST_DATABASE_URL`
  set: **672 passed** (56.8s). Two more than the 670 of the repair round;
  the delta is exactly develop's new `test_execution_lifecycle.py`
  machine passing beside the fence (da21a7bffb's provisioning of the I29
  lease-fence and #881 lifecycle machines holds).
- Step `Run extension lifecycle proof` — `python
  scripts/extension_lifecycle_proof.py --out`: **PROVED 13/13 stages,
  62/62 checks, exit 0**.
- `python scripts/check-formal-oracle-independence.py --base 4f8f40352d`:
  **OK**.
- `python scripts/check-m1-convergence-freeze.py --base 4f8f40352d`: **OK**
  (no unapproved new architecture island).

Named producer coverage-postgres (quality.yml:357-461), CI's ordering:

- Step `Migration suites against an unmigrated database` — `pytest
  tests/migrations` against fresh, unmigrated `maistro_mig`: **174
  passed** (243s; +1 over the 585cd8d round — the brief-FK
  installed-base module `test_workspace_tombstones_installed_base.py`
  from da21a7bffb, running its subprocess `alembic upgrade head` against
  a real server).
- Step `Apply the chain...` on `maistro_test`, then the full
  quality.yml:445-461 suite list in ONE pytest session: **7653 passed,
  99 skipped, 4 xfailed, 0 failed** (435s) — identical to the repair
  round's post-fix counts, including the repaired
  `personas/test_durable_store_pg.py::test_persona_migration_cascade_is_enforced_by_the_database_itself`
  (`pytest.raises(asyncpg.exceptions.RestrictViolationError)`, restored
  by 40f961d1ef; the node was also run alone: **PASSED**).
- CI's separate backlog invocation: **115 passed, 2 skipped**.
- Hive-conductor authority/journal durability with PG legs on —
  `test_workspace_authority.py` + `test_workspace_authority_durable.py`
  + `test_canonical_recovery_cadence.py` + `test_manual_fire_canonical.py`:
  **63 passed, 0 skipped** (the driver's DSN-less check-4 ran the same
  list as 52 passed / 11 skipped; with the DSN every PG leg runs).

Hygiene:

- `uv run ruff check .` and `uv run ruff format --check .`: pass
  (driver checks 1-2, 3688 files).
- `python scripts/check-suite-inventory.py` (ci.yml's full invocation):
  **21/21 suites match** the recorded inventory (37263 unique node IDs,
  0 duplicates, 0 byte-identical files).
- Closure keywords: 0 matches for `fixes|closes|resolves #` across all
  branch commit messages since the develop base; PR #2525 body says only
  "Refs #37".

## Acceptance map (AC -> executed evidence)

- AC-1 (same canonical ID/membership/Root on Hive and server, new-process
  PG restart) -> the green quality.yml ordering session + the 63-passed
  hive durable run at this head.
- AC-2 (unknown/deleted ids fail BEFORE writes, zero rows) -> fence tests
  in `projects/`, `workspaces/`, `persistence/`, all inside the
  7653-passed session.
- AC-3 (PG two-replica races cannot mint/preserve unauthorized Root/Run)
  -> `runs/` + persistence fence-race tests in the same session.
- AC-4 (missing/interrupted/corrupt journals; auditable quarantine) ->
  the 63-passed hive authority/journal run above.
- AC-5 (orphan disposition preserves provenance, no new admissions) ->
  orphan-disposition + tombstone tests in the green session, the
  brief-FK installed-base module in the 174-passed migrations run, and
  the fresh-DB chain apply to 071.
- AC-6 (#1419 representation map) ->
  `docs/architecture/WORKSPACE-DATA-OWNERSHIP-MAP.md` present; its
  presentation pins are inside the 63-passed hive run. The issue's
  closure-gate artifact assembly (CI link, exact merged SHA on GitHub)
  remains the driver's remit — no GitHub actions taken from this lane.
