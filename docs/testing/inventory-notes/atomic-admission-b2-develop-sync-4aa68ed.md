---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 develop-sync round 2: merge origin/develop 4aa68edc into auto-1893

## Frozen scope and reconciliation

This round processes only the assigned develop-sync repair for issue #1893 in
`auto-1893`, starting at `d9ea4f3b1671` and merging the one new develop commit
`4aa68edc0b6b` (EPIC M9-B governed extension registry / post-install
lifecycle, #2094). No new tests are added by this round; the merge introduces
develop's own `test_post_install_lifecycle.py` (36 core + 5 HTTP cases), which
develop's `954-extension-post-install-lifecycle.md` inventory note records.
The canonical `Goal -> Graph -> Run -> NodeRun -> Attempt` model, the immutable
admission ADRs and every quality gate definition are untouched by this round.

## Merge resolution

No conflicts: `git merge origin/develop` auto-merged 15 paths. The only
both-sides-touched src file, `packages/maistro-core/src/_vulture_whitelist.py`,
was verified by three-way inspection: develop's refactor side won the hunks it
owns (the `ExtensionInstallService` import is gone — the class no longer
exists in develop's refactored `extensions/service.py`, and the merged tree
takes develop's `extensions/*` wholesale because this branch never touched
them) while this branch's four `admission` entries and develop's
`InMemoryStrikeTracker` entries are all present in the merged file. Merge
committed as `214b00a7d8e2`. `scripts/check-merge-markers.py`: ok, no
conflict markers in tracked files. Quality ledgers: this branch touches only
`quality/reachability-baseline.json` and `quality/reachability-dispositions.json`;
develop's commit touches only `quality/shipped-surface-truth.json` (+60
extension-route rows) — no overlap, no row loss.

## Executed validation (this worktree, head 214b00a7d8e2)

- `uv run ruff check .`: all checks passed. `uv run ruff format --check .`:
  3270 files already formatted.
- CI-exact mypy (`packages/maistro-core|server|turing|canvas|bootstrap|
  registry|ext-sdk /src`): success, no issues in 892 source files.
- Focused: `uv run pytest packages/maistro-core/tests/runs/
  test_root_admission_identity.py packages/maistro-core/tests/tasks/
  test_admission_codec.py -q`: 201 passed, 3 skipped (PG legs off).
- Broader: `packages/maistro-core/tests` 15361 passed, 1037 skipped,
  3 xfailed; `packages/maistro-core/tests/extensions
  packages/maistro-server/tests` 1554 passed, 8 skipped; `packages/
  maistro-turing/tests packages/maistro-ext-sdk/tests` 357 passed; root
  `tests/ --ignore=tests/tools/registry` with CI env (`REQUIRE_AUTH=false
  MAISTRO_DRY_RUN=1`) **4971 passed, 129 skipped** — the CI `test` job's
  exact suite scope is green at this head. The lane brief's "test: failure"
  signal is stale: the captured check-runs at `d9ea4f3b1` show `test`
  **success** (run 38036708129, completed 2026-10-10T08:33:20Z, same SHA),
  confirmed again by read-only API at round start; the only failing check at
  that SHA is `exact-debt-ledger`.
- `uv run python scripts/check-suite-inventory.py` (CI-exact, no suite
  filter): ok, 17 suite(s) match the recorded inventory (31256 unique
  identities).
- CI-exact vulture (`packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'`): 1323 reviewed identities -> 1323 findings, ok — no
  unbanked identities, no vulture-ledger amendment needed.
- `uv run python scripts/check-shipped-surface-truth.py`: matrix complete.
- `RATCHET_BASE_REV=origin/develop uv run python scripts/
  check-ratchet-provenance.py`: FAIL — exactly the two known reachability
  sub-gates name `maistro.runs.admission_identity` and
  `maistro.tasks.admission_codec` as NEW unreachable modules/dispositions
  "not previously authorized" against the new trusted base `4aa68edc0b6b`.
  Verified directly: `4aa68edc0` does not modify
  `quality/ratchet-authorizations.json` (diff vs `1f328be96` touches only
  `quality/shipped-surface-truth.json`) and carries no grant covering these
  modules, so the documented external resolution stands: land the reachability
  grant on develop first (two-merge rule), then merge develop into
  `auto-1893`. No in-branch alternative exists: removing the candidate banking
  trips "current unreachable module missing from candidate baseline", and
  reaching the modules would be the production activation the issue forbids
  ("no baseline/grant/gate modifications to make an unwired slice green").

## Live-PG durability re-proof at this head

Disposable PostgreSQL 18.6 container (`pgvector/pgvector:pg18`, port 55993,
database `maistro_1893_r6`, removed after the round):

- `DATABASE_URL=postgresql://postgres@127.0.0.1:55993/maistro_1893_r6
  uv run alembic upgrade head`: real chain 001→062 (head).
- `MAISTRO_REQUIRE_PG_LEGS=1 MAISTRO_TEST_PG_DSN=MAISTRO_TEST_DATABASE_URL=
  postgresql://postgres@127.0.0.1:55993/maistro_1893_r6` focused run:
  **204 passed, 0 skipped**.
- Storage-contract probe on the migrated DB:
  `ck_task_idempotency_v2_identity` exists with exactly the shape
  `test_admission_codec.py` pins — the binding clause reads
  `((task_id IS NULL) AND (run_id IS NULL)) OR ((task_id IS NOT NULL) AND
  (run_id IS NOT NULL) AND (task_id = receipt_id))`. A v2 INSERT with the
  codec's binding shape (`task_id='rcpt-1'`, `run_id='run-1'`) is accepted
  (`INSERT 0 1`); a complete-but-one-sided v2 row (`task_id NULL`,
  `run_id='run-x'`) is rejected with `violates check constraint
  "ck_task_idempotency_v2_identity"` and lands 0 rows. Cleanup `DELETE 1`,
  residue `count = 0`.

## Outcome

B2 leaf acceptance evidence is complete and green at the merged head
`214b00a7d8e2`; the single remaining merge blocker (`exact-debt-ledger`
reachability provenance) is structural, outside this branch's authority, and
re-documented above against the new trusted base.
