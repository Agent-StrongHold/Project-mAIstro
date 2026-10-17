---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 verification round — job 6336fecb (fresh re-validation at c0c2f23eb; external two-merge block unchanged)

Snapshot: issue #1893 only; branch `auto-1893`, clean starting HEAD
`c0c2f23ebaed8aebc44de5de8c79de8ba2f55ed4` (docs-only delta versus the
previous round's end head `f07c1e922`). This round authors no production
code, no tests, no ledger rows, no grants and no gate files; the only
tree change is this note. Nothing was trusted from earlier rounds: every
gate, suite and database probe below was executed fresh.

## Named CI failure — `test:` — not reproducible, re-proven fresh at this head

Every Python leg of the `test` job (`.github/workflows/ci.yml:496-664`)
was re-executed at this head in the CI environment
(`REQUIRE_AUTH=false MAISTRO_DRY_RUN=1`, `RATCHET_BASE_REV=origin/develop`
where the job names it):

- `packages/maistro-core/tests` (full suite): 15416 passed, 1047 skipped, 3 xfailed
- `packages/maistro-server/tests`: 557 passed, 8 skipped
- `packages/maistro-turing/tests`: 210 passed
- `packages/maistro-turing/backend/tests`: 90 passed
- `packages/maistro-design/tests`: 572 passed, 1 skipped
- `packages/maistro-ext-harness/tests`: 273 passed
- `packages/maistro-ext-sdk/tests`: 147 passed
- `tests/ --ignore=tests/tools/registry`: 4971 passed, 129 skipped
- one-process leakage proof (`tests/` + hive backend + design): 9262 passed, 149 skipped
- `scripts/check-suite-inventory.py`: 17 suites, 31333 node IDs, ok
- `scripts/check-test-duplicates.py`: 1589 files, 0 duplicate groups, ok
- OpenAPI→generated-types coupling: `dump-hive-openapi.py` + `gen:api`
  then `git diff --exit-code` on `types.gen.ts` — no diff
- npm lint/build/test:ci legs carry: the branch's diff versus develop
  contains zero frontend files and zero `maistro-server`/hive-backend
  source changes; the backend behind the OpenAPI document passes inside
  the leakage leg above.
- `uv run mypy` (publish-set): Success, 894 source files
- driver pre-checks at this head: `ruff check .` clean, `ruff format
  --check .` 3277 files clean, focused admission suites 201 passed,
  3 skipped (PG legs skipped without a DSN — supplied live below)

## exact-debt-ledger — the one failing gate, unchanged and external

CI-exact invocations re-run this round:

- `RATCHET_BASE_REV=origin/develop uv run python
  scripts/check-ratchet-provenance.py` → exit 1, and the only failing
  sub-ratchets are reachability (`NEW unreachable module absent from
  trusted base and not previously authorized`) and
  reachability-dispositions (`NEW disposition absent from trusted
  ledger`), solely `maistro.runs.admission_identity` and
  `maistro.tasks.admission_codec`. All other sub-ratchets OK.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0, 1323
  reviewed identities = 1323 findings, `unclassified: 0`. No unbanked
  identities exist, so the CI-repair allowance to amend
  `quality/vulture-baseline.json` has nothing to act on and no amendment
  was made.
- `uv run python scripts/check-shipped-surface-truth.py` → exit 0.

Origin re-fetched this round: `origin/develop` is still `435dc193` (0
commits ahead of the branch base), so no develop sync is possible and
the two-merge rule still applies: `check-ratchet-provenance.py` reads
authorizations from the merge base, which carries zero admission
authorization rows, and issue #1893 explicitly forbids baseline/grant
edits that would green an unwired slice from the candidate side. The
documented resolution is unchanged: land the reachability authorization
on develop first, then merge develop into this branch. No in-lane repair
exists without violating the issue or the ratchet's own provenance
policy.

## Acceptance re-proven live (PG 18, fresh disposable database)

- Created `maistro_1893_r3` in the disposable `auto-1893-pg`
  (pgvector/pgvector:pg18) container and ran the real chain
  `uv run alembic upgrade head` (001 → 062) against it via
  `DATABASE_URL`.
- Focused admission suites with `MAISTRO_REQUIRE_PG_LEGS=1` and both
  `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` pointed at the
  fresh database: **204 passed, 0 skipped** (dual-pool raw-vs-production
  codec identity included).
- Direct `psql`-equivalent asyncpg probes against the migrated schema:
  `pg_get_constraintdef('ck_task_idempotency_v2_identity')` read live
  and matches the contract — binding represented as
  `((task_id IS NULL) AND (run_id IS NULL)) OR ((task_id IS NOT NULL)
  AND (run_id IS NOT NULL) AND (task_id = receipt_id))`, and
  `(acknowledged_at IS NULL) OR (task_id IS NOT NULL AND run_id IS NOT
  NULL)`. INSERT probes: production-encoder shape (task_id = receipt_id
  + run_id) ACCEPTED; `task_id ≠ receipt_id`, `run_id` without
  `task_id`, `task_id` without `run_id`, and acknowledged-without-pair
  each REJECTED by the CHECK; acknowledged-with-pair ACCEPTED; 0 residue
  rows from rejected probes.
- Source re-read at this head (not from prior notes):
  `encode_admission_record` emits `task_id`/`run_id` together from the
  binding, both NULL when unbound
  (`packages/maistro-core/src/maistro/tasks/admission_codec.py:260-294`);
  `decode_admission_record` re-derives the header from the row and
  rejects disagreement structurally as `invalid_header`
  (`admission_codec.py:233-258`);
  `AdmissionRecord.__post_init__` raises on
  `binding.receipt_id != envelope.receipt_id`
  (`packages/maistro-core/src/maistro/runs/admission_identity.py:291-293`);
  receipt-only and one-sided legacy evidence decode to
  `partial_legacy_binding`, never to an invented identity
  (`admission_codec.py:567-660`), pinned by
  `test_legacy_receipt_only_row_is_partial_not_unbound` and
  `test_v2_task_without_run_is_corruption_not_unbound`.
- Diff scope versus develop re-checked: only the two admission modules,
  `_vulture_whitelist.py`, the two test files, quality reachability
  rows and docs — no SQL mutation, HTTP or queue changes.

## Verdict

All issue-acceptance criteria are proven at this head; the named `test:`
CI failure does not reproduce under CI's exact invocations. The sole
red is the exact-debt-ledger reachability provenance, structurally
unfixable in-lane by the two-merge rule while `origin/develop` carries
no authorization rows — external owner action, then a develop merge into
this branch.
