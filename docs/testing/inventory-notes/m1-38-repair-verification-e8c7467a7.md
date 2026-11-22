# M1-A2 CI-repair verification record (head e8c7467a7)

Independent re-validation of the two CI failures reported at 9f84000bf (Quality gate,
Pillars 1–4/7/8; Coverage gate, publish-set floor + diff coverage). Nothing from the
prior session's claims was inherited: every gate below was re-executed at this head in
this round, against reachable production behavior. No code changes were required — the
repair itself is commit e8c7467a7 (memory conformance leg + workspace-mismatch refusal
test + the superseded `design_coverage@33.9095` grant prune); this note only records the
re-executed evidence.

Postgres for every PG leg: lane container `maistro-repair-pg` (pgvector/pg18, port
55941), fresh scratch DB `acstate38` migrated with `uv run alembic upgrade head`
(through 042) exactly as the quality job does. MinIO for the archive producer:
`auto-1187-cov-minio` (port 55900, minioadmin), the same env shape as
`coverage-archive`.

## The two failed CI gates, re-executed

- **Quality gate, ac-state step** (the actual failure at 9f84000bf):
  `MAISTRO_TEST_PG_DSN=…acstate38 DATABASE_URL=…acstate38 uv run python
  scripts/check-ac-state.py --run-tests --ratchet --mandate <base>` — exit 0 with
  "OK: 10 debt counters sit exactly on their ceilings … OK: every criterion this
  change declares is proven … adds no spec, decision or criterion-less document",
  run against BOTH possible mandate bases: the merge-base ca4caec7d and the develop
  tip 9e9f5037e (the job manifest base).
- **Coverage gate, diff-coverage step**: reproduced with CI's producer scope — full
  core suite under `coverage run --branch` with `MAISTRO_REQUIRE_PG_LEGS=1` (the
  union of the `coverage-unit` and `coverage-postgres` producers for the changed
  files), plus the `coverage-archive` (MinIO, `MAISTRO_REQUIRE_S3_LEGS=1`),
  canvas-with-PG, evolve, rsi, bootstrap, and `maistro-server` producers.
  `scripts/check-diff-coverage.py coverage.xml --base <base>` — exit 0 at both bases:
  "7 changed file(s) measured, 3 exempt (test code), ok: every measured file … at or
  above 90% lines / 80% branch arcs". The three files named in the CI failure now
  measure `scope_store.py` 94% (was 16.7%), `pg_scope_store.py` 95% (was 75%),
  `sqlite_scope_store.py` 95% (was 75%); `container.py` 96%, `workspaces/store.py`
  95%, `memory/context_assembly.py` 100%, `maistro_server/api/projects.py` 96%.
- **Coverage gate, publish-set floor**: `coverage report --fail-under=87` over the
  publish-set sources — 93% (exit 0), also 93% scoped to the five publish-set
  packages before the server append, matching the CI evaluation order.

## Other quality-job pillars re-run at this head

ruff check + format (pass); radon CC ratchet, xenon (0 block violations, baseline
77), vulture per-identity ledger (`1412 reviewed identities -> 1412 findings`,
0 unclassified — no ledger amendment needed this round), doc-links, suite-inventory,
enumerations, credential-authority, wiring-reads, agent-store-writes,
contract-markers, convergence-matrix, reachability dispositions, security/image
inventory, backlog consistency, bump_version --check (all pass); `mypy --strict
packages/maistro-core/src` — Success in 637 files; `formal/` property suite —
663 passed; `tests/fitness` — 7 passed; interrogate floors (38/45/63/46) — pass.

## pyright ratchet: 22 vs baseline 21 — measured, not caused by this branch

With today's unpinned pyright (1.1.414, the same resolution CI's
`uv pip install pyright` performs), the count at this head is 22. Three measurements
attribute the +1 to tool-version drift on files this branch never touched:

1. Zero diagnostics (error or warning) fall in any file changed by this branch's
   diff (projects/*, workspaces/store.py, container.py, memory/context_assembly.py,
   maistro_server/api/projects.py).
2. Under one identical binary and flag set (`--pythonpath .venv/bin/python`), the
   merge-base ca4caec7d measures **28** and the develop tip 9e9f5037e measures
   **28** — the branch *reduces* the count by 6; the ratchet would fail on develop
   itself under this pyright.
3. The historical baseline (21) predates this pyright release; the gate is unpinned
   in CI by design, so the drift is a repository-wide condition, not a candidate
   regression. Fixing unrelated legacy findings is outside this lane's scope.

## Acceptance battery (issue #38) re-executed with PG legs forced

- `packages/maistro-core/tests/projects/test_scope_store_conformance.py` with
  `MAISTRO_REQUIRE_PG_LEGS=1` against migrated PG: **75 passed, 2 skipped** (both
  skips are the documented by-design ones: PG enforces owning-runs deletion via
  foreign key not predicate; the memory backend drains a Workspace in one pass so
  the `_MAX_PURGE_PASSES` bound does not exist there). The suite parametrizes
  memory + sqlite + postgres, covering root idempotence/immutability, acyclic
  no-cross-Workspace moves, #1147 concurrent opposite moves and locked/unlocked
  writer collision, #1148 one-row membership writes, revocation racing a delegated
  merge, re-grant, pre-#1148 SQLite in-place upgrade, downward-only resource
  visibility with explicit denies, and fail-closed refusals.
- `packages/maistro-core/tests/projects` + `tests/workspaces`: **248 passed,
  4 skipped** (includes `test_denies_accumulate_and_win_over_descendant_grants` —
  ancestor deny beats descendant grant — and
  `test_workspace_creation_provisions_exactly_one_persisted_root_project`).
- Run-scope survival/immutability: `tests/runs/test_spine_conformance.py` with
  PG legs required — **361 passed**; `test_retention_scope_conformance.py` +
  `test_store.py` — 33 passed, 2 skipped.
- Full core suite under coverage (PG legs on): **11099 passed**, 1 failed —
  `test_container_postgres.py::test_an_unreachable_server_is_an_error_not_a_fallback`,
  a WSL-only artifact (port-1 connect hangs past the pytest timeout; CI refuses the
  connection instantly); it touches none of this branch's files.
- `maistro-server` suite: **393 passed** (includes the projects API tests).

## Local-environment reconciliations (not repo changes)

`maistro_bootstrap` and `maistro_evolve` are workspace members CI installs via
`uv sync --locked --all-extras` / the in-job `uv pip install`; this sandbox's
`uv sync --locked --extra dev` omits them, so both were installed editable before
the mypy/evolve runs. The five `import-not-found` mypy errors seen before that
install were all `maistro_bootstrap` resolution failures, not code findings;
after the install mypy reports Success.
