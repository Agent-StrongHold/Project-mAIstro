---
inventory-delta:
  packages/maistro-core/tests: +0
---
# Issue #1893 repair round at e655ec85

Snapshot: branch `auto-1893`, head `e655ec85000462fb753fbb09ab520c85cc164e1b`,
develop base `ab8b3737fa64f8d840f421ef87ca506c509444ff` (fresh-fetched;
origin/develop unchanged — nothing to merge). Clean worktree, no tree edits
this round: validation-only round plus this note. Only issue #1893 is processed.

No tests were added; the `inventory-delta` is zero.

## exact-debt-ledger job (`.github/workflows/vulture-ratchet.yml:30`), CI-exact legs

Environment restored with `uv sync --locked --all-extras` (CI step
`vulture-ratchet.yml:75`; the driver's `--extra dev` sync had removed
maistro-bootstrap/playwright).

1. `RATCHET_BASE_REV=origin/develop uv run python scripts/check-ratchet-provenance.py`
   → **exit 1** (reproduced). Failing ratchets: `reachability-dispositions`
   and `reachability` — for exactly `maistro.runs.admission_identity` and
   `maistro.tasks.admission_codec`: "NEW disposition absent from trusted ledger
   and not covered by an already-landed reachability authorization" x2 and
   "NEW unreachable module absent from trusted base and not previously
   authorized" x2. All eight other ratchets (adr-status-language,
   citation-status, promotion-surface, shell-execution, contract-markers,
   enumerations, lifecycle, …) OK. Cause: the reachability authorization
   (`quality/ratchet-authorizations.json`, added in 6af21c54e) plus the
   baseline rows (`quality/reachability-baseline.json:131,147`) and the
   CONNECT disposition group `runs-root-admission-contracts`
   (`quality/reachability-dispositions.json:604-614`) exist only on this
   branch; `load_authorizations` reads grants from the merge base
   (`scripts/ratchet_provenance.py` two-merge rule), and origin/develop is
   still ab8b3737. The grant therefore cannot authorize its own introduction.
   The only repair is develop-side: land the grant rows on origin/develop
   first (owner/integration action — push is outside worker authority), then
   merge develop into auto-1893 and re-run the gate.
2. `uv run python scripts/check-shipped-surface-truth.py` → exit 0.
3. `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
   → exit 0: 1322 reviewed == 1322 findings, `unclassified: 0`,
   `never_allowlist: 0`. No unbanked identities, so no
   `quality/vulture-baseline.json` amendment is applicable this round.

## Named CI failure `test: failure` — disproven again at this head

All Python legs of `.github/workflows/ci.yml` job `test` re-run with CI-exact
env (`REQUIRE_AUTH=false`, `MAISTRO_DRY_RUN=1`) at e655ec85:

- `packages/maistro-server/tests` → 557 passed, 8 skipped
- `packages/maistro-turing/tests` → 210 passed
- `packages/maistro-turing/backend/tests` → 90 passed
- `packages/maistro-design/tests` → 572 passed, 1 skipped
- `packages/maistro-ext-harness/tests` → 273 passed
- `packages/maistro-ext-sdk/tests` → 147 passed
- `tests/ --ignore=tests/tools/registry` → 4982 passed, 135 skipped
- `packages/hive-conductor/backend/tests` → 3626 passed, 19 skipped
- cross-suite one-process (`tests/ packages/hive-conductor/backend/tests
  packages/maistro-design/tests -q --timeout=60`) → 9273 passed, 155 skipped
- `scripts/check-suite-inventory.py` (full, 17 suites, 31451 node IDs) → ok
- `scripts/check-test-duplicates.py` → ok

The npm/frontend legs were not re-run: `git diff --name-only ab8b3737..HEAD`
touches no frontend, package.json or OpenAPI-producing server file, so those
legs cannot be affected by this branch's diff.

## Issue acceptance re-proof (independent this round)

- `packages/maistro-core/src/maistro/tasks/admission_codec.py` read in full:
  AdmissionRowHeader frozen+slots with exactly the six issue-named fields;
  `decode_admission_header`; `decode_admission_record(row, *, header)`
  re-derives the header from the row and rejects disagreement
  (`invalid_header`); `encode_admission_record` returns a fresh flat
  SQL-parameter mapping; `AdmissionDecodeCode` has exactly the six issue
  values; every `AdmissionRowDecodeError` raiser uses `raise … from None`,
  messages name column + failure class only, and `scope_key` is kept only
  after `[0-9a-f]{64}` validation (else `None`). Legacy `completed_at` is
  never read (grep: docstrings only).
- No guessed identity: one-sided pairs, bound-pair-without-receipt,
  receipt-only rows and unreadable evidence all raise
  `partial_legacy_binding`; no task/run/receipt id is ever fabricated.
- All ten issue-named prospective tests exist
  (`tests/tasks/test_admission_codec.py:128,154,171,187,205,220,231,262,294,448`);
  the header/full-decode separation tests assert preserved scalar evidence
  after `INVALID_SNAPSHOT` and `PARTIAL_LEGACY_BINDING` failures (:205-231).
- Focused run (pure): `uv run pytest
  packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -q`
  → 201 passed, 3 skipped.
- Durability legs live: disposable DB `adm1893_r1792230246` created in the
  running pg18 container, migrated with real `uv run alembic upgrade head`
  (chain 001→063; `alembic current` = `063 (head)`), then the same focused
  run with `MAISTRO_REQUIRE_PG_LEGS=1 MAISTRO_TEST_PG_DSN=…
  MAISTRO_TEST_DATABASE_URL=…` → **204 passed, 0 skipped**. Includes
  `test_raw_and_production_pool_codecs_read_identical_text_snapshots`
  (unbound/bound/acknowledged) asserting same database/server/port with
  distinct backend pids between the production `_register_json_codecs` pool
  and the raw pool.
- Scope: src diff vs base is exactly `admission_codec.py`,
  `runs/admission_identity.py`, `_vulture_whitelist.py`; grep for
  alembic/maistro_server/queue/http/router/migration paths in the full diff →
  none. No SQL mutation, HTTP mapping or queue change.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py` → Success.
- `uv run ruff check .` and `uv run ruff format --check .` → pass (driver
  check-1.log / check-2.log at this head).

## Residual blocker (unchanged, precisely identified)

`exact-debt-ledger` step 1 stays red until the grant lands on origin/develop
(two-merge rule) — an owner-side push followed by a develop merge into
auto-1893. Everything provable inside the worktree is proven above.
