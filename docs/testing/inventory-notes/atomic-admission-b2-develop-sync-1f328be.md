---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 develop-sync round: merge origin/develop 1f328be into auto-1893

## Frozen scope and reconciliation

This round processes only the assigned develop-sync repair for issue #1893 in
`auto-1893`, starting at the conflicted in-progress merge of
`1f328be96a5ec4cc0d6c8469c29dfb7e3f4de23a` (current `origin/develop`) into
`943db286d08623dc58dede88804371ebf90f243f`. No new tests are added by this
round; the merge itself introduces develop's #358 audit-pagination tests
(alembic 062, `audit_pages.py`, hive audit routes/frontends), which develop's
own inventory notes record — the full `scripts/check-suite-inventory.py`
(17 suites, 31233 identities) passes at the merged head, so no candidate-side
baseline edit is needed. The canonical `Goal -> Graph -> Run -> NodeRun ->
Attempt` model, the immutable admission ADRs (081426-1f7c, 082526-7f02,
082826-b601, 082826-d9f5) and every quality gate are untouched by this round.

## Merge resolution

One conflicted path: `packages/maistro-core/src/_vulture_whitelist.py` — a
both-sides-added import hunk (HEAD: `maistro.runs.admission_identity.
AdmissionAssessment` from #1851/#1893; develop: `maistro.protocols.memory.
AuditLog` from #358). Resolved by keeping both lines in isort order; both
names are referenced by the whitelist body (`AuditLog.get_page`;
`AdmissionAssessment.MISMATCH`/`REPLAYED`/`PENDING`/`TAKEOVER`/
`REPLACE_EXPIRED`/`LEGACY_UNRESOLVED`). Merge committed as `9cec39232f09`.
`scripts/check-merge-markers.py`: ok, no conflict markers in tracked files.

## Executed validation (this worktree, head 9cec39232f09)

- `uv sync --locked --extra dev`: ok.
- `uv run ruff check .`: all checks passed.
- `uv run ruff format --check .`: 3270 files already formatted.
- CI-exact mypy (`packages/maistro-core|server|turing|canvas|bootstrap|
  registry|ext-sdk /src`): success, no issues in 892 source files. The two
  changed src files (`tasks/admission_codec.py`, `runs/admission_identity.py`)
  are clean; remaining strict-mode findings live only in test files, which no
  CI mypy job checks.
- Focused: `uv run pytest packages/maistro-core/tests/runs/
  test_root_admission_identity.py packages/maistro-core/tests/tasks/
  test_admission_codec.py -q`: 201 passed, 3 skipped (PG legs off).
- Broader merge-affected suites: `packages/maistro-core/tests` 15347 passed,
  1037 skipped, 3 xfailed; `tests/migrations` 38 passed, 122 skipped;
  `packages/hive-conductor/backend/tests` 3626 passed, 19 skipped; root
  `tests/ --ignore=tests/tools/registry` 4971 passed, 129 skipped;
  `packages/maistro-server/tests packages/maistro-turing/tests
  packages/maistro-ext-sdk/tests` 893 passed, 8 skipped. The captured CI
  check-runs at 943db show the `test` job **success** — the lane brief's
  "test: failure" signal is stale, and the job's suite scope passes locally
  at this head.
- `uv run python scripts/check-suite-inventory.py` (CI-exact, no suite
  filter): ok, 17 suite(s) match the recorded inventory.
- CI-exact vulture (`packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'`): 1323 reviewed identities -> 1323 findings, ok — no
  unbanked identities, so no vulture-ledger amendment is needed this round.
- `uv run python scripts/check-shipped-surface-truth.py`: matrix complete.
- `RATCHET_BASE_REV=origin/develop uv run python scripts/
  check-promotion-surface-provenance.py` and `check-promotion-surface.py`:
  ok (270 promotion-path modules, 74 tolerated, no expansion).
- `RATCHET_BASE_REV=origin/develop uv run python scripts/
  check-ratchet-provenance.py`: FAIL — exactly the two known reachability
  sub-gates (`check-reachability-provenance.py`,
  `check-reachability-dispositions-provenance.py`) name
  `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` as
  NEW unreachable modules/dispositions "not previously authorized". This is
  the two-merge rule: `scripts/ratchet_provenance.py::load_authorizations`
  reads `quality/ratchet-authorizations.json` from the trusted base only, and
  develop @1f328be carries 11 reachability grants, none covering these two
  modules (verified directly against `git show 1f328be:quality/ratchet-
  authorizations.json`). No in-branch alternative exists: removing the
  candidate banking trips "current unreachable module missing from candidate
  baseline", and reaching the modules would be the production activation the
  issue forbids. Resolution remains the documented external step: land the
  reachability grant on develop first, then merge develop into auto-1893.

## Live-PG durability re-proof at this head

Disposable PostgreSQL 18 container (`pgvector/pgvector:pg18`, removed after
the round) hosting database `maistro_1893_r4`:

- `DATABASE_URL=postgresql://postgres@127.0.0.1:55999/maistro_1893_r4
  uv run alembic upgrade head`: real chain 001→062 (head), including the
  merge-introduced 062 (ordered exact-scope audit cursor indexes, #358).
- `MAISTRO_REQUIRE_PG_LEGS=1 MAISTRO_TEST_PG_DSN=MAISTRO_TEST_DATABASE_URL=
  postgresql://postgres@127.0.0.1:55999/maistro_1893_r4` focused run: **204
  passed, 0 skipped** — matching the prior round's live-PG result, now on the
  062 chain.
- Storage-contract probe on the migrated DB: `ck_task_idempotency_v2_identity`
  exists with exactly the shape `test_admission_codec.py` pins
  (`(task_id IS NULL AND run_id IS NULL) OR (task_id IS NOT NULL AND run_id
  IS NOT NULL AND task_id = receipt_id)`). A v2 INSERT with the codec's
  binding shape (`task_id='rcpt-1'`, `run_id='run-1'`) is accepted
  (`INSERT 0 1`); a one-sided binding (`task_id NULL`, `run_id` set) is
  rejected with `violates check constraint "ck_task_idempotency_v2_identity"`.
  Cleanup `DELETE 1`, residue `count = 0`.

## Outcome

B2 leaf acceptance evidence is complete and green at the merged head; the
single remaining merge blocker (`exact-debt-ledger` reachability provenance)
is structural, outside this branch's authority, and documented above.
