---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 repair round — job bbae499c (fresh validation at e519c6df; sole residual remains the external two-merge grant)

Snapshot: issue #1893 only; branch `auto-1893`, clean starting HEAD
`e519c6dfcf41415a1c25490b3c88c3aa1412684c`. This round authors no
production code, no tests, no ledger rows, no grants and no gate files;
the only tree change is this note. Nothing was trusted from earlier
rounds: every gate, suite and database probe below was executed fresh in
this round, and the review findings were re-checked against source at
this head rather than against prior claims.

## Dispatched CI failure `test:` — re-proven green at this head

The captured remote check-runs at exactly this head
(`commits/e519c6dfcf41…/check-runs`, dispatch-context.json) already show
the `test` job **completed / success** (started 2026-10-10T19:55:19Z);
the failure in the merge-queue evaluation is not present at this
content. Re-proven fresh locally this round under the CI job's
environment (`REQUIRE_AUTH=false MAISTRO_DRY_RUN=1`):

- `packages/maistro-core/tests` (full): **15416 passed, 1047 skipped,
  3 xfailed** in 242s — identical to the recorded baseline
- `packages/maistro-server/tests` + `maistro-turing/tests` +
  `maistro-turing/backend/tests` + `maistro-design/tests` +
  `maistro-ext-harness/tests` + `maistro-ext-sdk/tests`: **1849 passed,
  9 skipped**
- `tests/ --ignore=tests/tools/registry`: **4971 passed, 129 skipped**
- `uv run mypy` (AGENTS.md publish-set invocation): **Success, no issues
  in 894 source files**
- `scripts/check-suite-inventory.py`: **ok, 17 suite(s) match the
  recorded inventory**; `scripts/check-test-duplicates.py`: 1589 files,
  0 duplicate groups, ok
- driver pre-checks at this head (job check-*.log): `ruff check .` clean,
  `ruff format --check .` 3277 files clean, focused admission suites 201
  passed 3 skipped without a DSN (supplied live below)

## exact-debt-ledger — the one red gate, unchanged and external

CI-exact invocations re-run this round:

- `uv run python scripts/check-ratchet-provenance.py` → exit 1; the only
  failing sub-ratchets are reachability and reachability-dispositions,
  solely for `maistro.runs.admission_identity` and
  `maistro.tasks.admission_codec` ("NEW unreachable module absent from
  trusted base and not previously authorized" x2 / "NEW disposition
  absent from trusted ledger" x2). Shell-execution, contract-markers,
  enumerations and lifecycle sub-ratchets all OK.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → **exit 0**, 1323
  reviewed identities = 1323 findings, `unclassified: 0`. There are no
  unbanked vulture identities, so the CI-repair allowance to amend
  `quality/vulture-baseline.json` has nothing to act on; no amendment
  was made and none was needed.
- `uv run python scripts/check-shipped-surface-truth.py` → exit 0.

Origin re-fetched this round: `origin/develop` is still `435dc193` (0
new commits; `git merge-base --is-ancestor origin/develop HEAD` holds,
so there is no develop-sync conflict to resolve) and
`origin/develop:quality/ratchet-authorizations.json` carries **0**
admission rows. The two-merge rule therefore still applies:
`check-ratchet-provenance.py` reads authorizations from the merge base,
which authorizes nothing for these modules, while issue #1893 explicitly
forbids baseline/grant/gate modifications that would green an unwired
slice from the candidate side. The documented resolution is unchanged
and external to this branch: land the reachability authorization on
develop first, then merge develop into `auto-1893`. No in-lane repair
exists without violating the issue or the ratchet's own provenance
policy.

## Independent-review findings (Codex, 2026-10-05 against 0d663a48e8) re-verified as fixed at this head

Each P-finding was checked against source and tests at this head; all
are addressed with named regression tests in
`packages/maistro-core/tests/tasks/test_admission_codec.py`:

1. **P1 wire-or-authorize the codec** — both new modules now carry
   reachability baseline rows + dispositions; the residual provenance
   failure is the external two-merge case above, exactly the path the
   review named ("land the reachability authorization separately").
2. **missing `request_snapshot` raised raw KeyError** —
   `_decode_legacy_record` calls
   `_require_columns(row, ("request", …))` before subscription
   (`admission_codec.py:601-606`); pinned by
   `test_missing_legacy_request_is_unsupported_schema`.
3. **lone-surrogate TEXT** — `_parse_snapshot` requires
   `snapshot.text.encode("utf-8")` inside the typed failure path
   (`admission_codec.py:409-411`, `UnicodeEncodeError ⊂ ValueError`);
   pinned by `test_non_utf8_snapshot_is_a_safe_typed_failure` and the
   dual-pool `test_raw_and_production_pool_codecs_read_identical_text_snapshots`.
4. **float `format_version` laundering** — both
   `AdmissionRowHeader.__post_init__` (`admission_codec.py:153-160`) and
   `_coerce_format_version` reject non-`int`/`bool`; pinned by the
   `bad_format` parametrization including `1.0` and
   `test_invalid_scalar_headers_fail_closed`.
5. **deep-nesting RecursionError escapes typed failure** —
   `_parse_snapshot` catches `RecursionError`
   (`admission_codec.py:415`); pinned by
   `test_excessive_snapshot_nesting_is_a_safe_typed_failure`.
6. **whitespace-only legacy task evidence** — `_legacy_evidence`
   rejects values not equal to their own strip
   (`admission_codec.py:655-660`); pinned by
   `test_legacy_bound_evidence_rejects_whitespace_without_normalizing`.
7. **float precision loss (`9007199254740993.0` → `…992.0`)** —
   `_parse_snapshot` compares the original and normalized text under
   `parse_float=Decimal` and rejects any drift
   (`admission_codec.py:412-413`); pinned by
   `test_lossy_snapshot_numbers_are_safe_typed_failures` /
   `test_exact_snapshot_numbers_survive_normalization`.

## Acceptance re-proven live (PG 18, fresh disposable database)

- Created `maistro_1893_r4` in the disposable `auto-1893-pg`
  (pgvector/pgvector:pg18) container and ran the real chain
  `uv run alembic upgrade head` (001 → 062) against it via
  `DATABASE_URL`; `alembic current` = `062 (head)`.
- Focused admission suites with `MAISTRO_REQUIRE_PG_LEGS=1` and both
  `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` pointed at the
  fresh database: **204 passed, 0 skipped**.
- Live `pg_get_constraintdef('ck_task_idempotency_v2_identity')` read
  from the migrated schema matches the migration-055 contract:
  `(task_id IS NULL AND run_id IS NULL) OR (task_id IS NOT NULL AND
  run_id IS NOT NULL AND task_id = receipt_id)` and
  `(acknowledged_at IS NULL) OR (task_id IS NOT NULL AND run_id IS NOT
  NULL)`. asyncpg INSERT probes: production-encoder shape (task_id =
  receipt_id + run_id) ACCEPTED; acknowledged-with-pair ACCEPTED;
  `task_id ≠ receipt_id`, `run_id` without `task_id`, `task_id` without
  `run_id`, and acknowledged-without-pair each REJECTED by the CHECK
  (`asyncpg.exceptions.CheckViolationError`, constraint named); probed
  rows cleaned to **0 residue**.
- Diff scope versus develop re-checked by name-status: only the two
  admission modules, `_vulture_whitelist.py`, the two test files,
  quality reachability rows (+2/+11 lines) and docs — no SQL mutation,
  HTTP mapping or queue change, and no OpenAPI surface delta.

## Verdict

Every in-branch acceptance criterion of #1893 is proven at this head,
and the dispatched `test:` failure does not exist at this content (CI
success captured at this SHA; every Python leg re-executed green with
baseline-identical counts). The sole red is exact-debt-ledger's
reachability provenance, structurally unfixable in-lane by the two-merge
rule while `origin/develop` carries zero authorization rows — external
owner action (land the grant on develop), then merge develop into this
branch. This round makes no gate, ledger, grant or production edits.
