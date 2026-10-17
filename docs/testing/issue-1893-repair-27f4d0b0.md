# Issue #1893 repair validation at 27f4d0b0

## Frozen scope

- Assigned issue: #1893 only; worktree `/home/dev/Git/wt/auto-1893`.
- Starting HEAD: `27f4d0b078f1c1174528b6631e50713763413dfa` (clean).
- Dispatch base: `3c761d14db944a727fa0744444bc67cfe36d49f7`.
- Evidence: supplied job `67a9ca6483244b649ccdf8fd1abb7215`, its captured
  dispatch context and check-0 through check-4 logs; no GitHub refresh.
- Production/test review scope: `maistro/tasks/admission_codec.py`,
  `maistro/runs/admission_identity.py`, their two focused test files, adjacent
  evidence serialization, schema, ADRs and CI gate definitions.
- Allowed edit scope: those production/test files if an actual defect is
  reproduced, this validation note, inventory note if tests change, and
  `quality/vulture-baseline.json` only for evidenced retained identities.
  No other ledger, grant, gate, activation, or ownership changes.

## Initial evidence and ambiguity

The supplied driver logs report dependency sync, ruff check/format, focused
201 passed / 3 skipped, and suite inventory 16466 passing. They are not live PG
acceptance. The generic `test: failure` has no traceback in these logs. Assume
this round is validation-first: reproduce before altering code. Historical
reachability provenance findings must be checked at the supplied current refs,
not assumed fixed. Stage-only codec work remains distinct from production
activation and parent closeout.

## Results

- Both dispatch base and `origin/develop` resolve to
  `3c761d14db944a727fa0744444bc67cfe36d49f7`; no unresolved refs used.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: PASS, 1323 reviewed
  identities / 1323 findings, zero unclassified. No ledger amendment warranted.
- `RATCHET_BASE_REV=3c761d14db944a727fa0744444bc67cfe36d49f7 uv run python
  scripts/check-ratchet-provenance.py`: FAIL (exit 1). Both
  `maistro.runs.admission_identity` and `maistro.tasks.admission_codec` are new
  unreachable modules and new dispositions without trusted-base authorization.
  Other provenance subchecks passed. This reproduces the historical blocker;
  it cannot be repaired by the permitted Vulture ledger amendment.

- Import search across `packages/**/*.py` confirms no production consumer of
  `admission_codec`; `admission_identity` is imported only by that codec,
  tests and the Vulture whitelist. Tests are not runtime reachability.
- Captured check-runs contain a `test` failure for linked #1855 head
  `3f2c79a70d9e1b0b6b6ffc99562cb35db5326828`, with null output text/summary;
  this is not an assigned-head traceback. The generic reported failure is
  UNRESOLVED, not grounds for a speculative production repair.
- Reviewed repository instructions, documentation authority map, codec/DTO
  implementations and both focused suites. ADR-082526-7f02 preserves immutable
  admission provenance and Attempt-owned dispatch; no authority change is
  permitted to make an inactive contract slice reachable.

### Real PostgreSQL validation

Created dedicated disposable DB `maistro_1893_67a9` in the existing local
`maistro-postgres` container (host port 5433), using its configured credentials
without recording them. Set `DATABASE_URL`, `MAISTRO_TEST_PG_DSN` and
`MAISTRO_TEST_DATABASE_URL` to that same DB and `MAISTRO_REQUIRE_PG_LEGS=1`.

- `uv run alembic upgrade head`: PASS, empty DB through real chain 001 to 062.
- `uv run pytest packages/maistro-core/tests/runs/test_root_admission_identity.py
  packages/maistro-core/tests/tasks/test_admission_codec.py -x -q
  -o junit_family=legacy --junitxml=/tmp/maistro-1893-67a9-pg.xml`:
  **204 passed, 0 skipped** (204 collected).
- Server version: PostgreSQL 18.6. SQL after tests: revision 062,
  `task_idempotency` rows = 0; `canonical_runs` rows = 0.
- The three PG cases insert one actual admission row each, verify exact TEXT
  through independent raw/production-codec pools, exercise unbound/bound/
  acknowledged states, and inject escaped surrogates into each snapshot column.
  They establish codec storage behavior, NOT authorized Run admission, model
  materialization, or a Run JSONB payload object (no Run is inserted).
- Migration downgrade/reversibility was not executed; this is forward-chain
  codec evidence, not B1 migration acceptance.

Session evidence from the JUnit properties (server `172.20.0.2/32:5432`,
DB `maistro_1893_67a9`):

| State | Production PID | Raw PID | Persisted rows |
| --- | ---: | ---: | ---: |
| unbound | 94368 | 94370 | 1 |
| bound | 94371 | 94372 | 1 |
| acknowledged | 94373 | 94374 | 1 |

The dedicated DB remains migrated and empty of admission/Run rows for inspection.

### Other executed checks

All commands below ran at the starting production source SHA; only this report
changed in this round.

- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 3277 files already formatted.
- `uv run mypy packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: PASS (2 files).
- `uv run python scripts/check-shipped-surface-truth.py`: PASS.
- `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: PASS, 16466 unique collected nodes, no duplicates.
- `uv run pytest packages/maistro-core/tests/tasks
  packages/maistro-core/tests/runs -x -q`: PASS, 1918 passed / 310 skipped,
  2228 collected. This broader run intentionally had no PG environment;
  skipped legs are not durability evidence. Six aiosqlite worker-thread
  `Event loop is closed` warnings occurred in `test_sqlite_store.py`; they
  did not fail this invocation and are not attributed to the inactive codec.

### Acceptance assessment

The focused 204-node run executes all ten prospective codec contracts:

| Criterion | Executed evidence / limit |
| --- | --- |
| Immutable exact v2 DTOs; fresh flat mapping; snapshot bytes | `test_v2_round_trip_preserves_all_snapshot_bytes` (3 states), `test_encode_returns_a_fresh_flat_mapping`; identity suite freeze checks |
| Owner token UUID .hex only at storage, safe errors | `test_owner_token_is_hex_at_storage_only`, strict generation and repr checks |
| Bound, unbound, partial legacy distinguished without invented identity | `test_legacy_binding_unbound_and_partial_are_distinct`, receipt-only and pair-without-receipt rejection tests |
| Expired legacy header preserves evidence | `test_expired_legacy_header_does_not_invent_missing_identity`; no clock or expiry decision introduced |
| Header expiry survives bad snapshot | `test_header_preserves_expiry_even_when_legacy_snapshot_decode_fails` |
| Header fingerprint survives partial binding | `test_header_preserves_fingerprint_even_when_legacy_binding_is_partial` |
| Unknown format/scalar mismatch fail closed | `test_unknown_format_cannot_be_reinterpreted_as_legacy`, scalar mismatch and invalid-header tests |
| Tagged nonfinite evidence and stored fingerprint preserved | `test_tagged_nonfinite_snapshots_round_trip_without_fingerprint_change`; no fingerprint recalculation |
| Invalid/duplicate/nonobject/nonfinite JSON rejected safely | `test_invalid_and_duplicate_json_is_rejected`, numeric-loss, deep-nesting and Unicode corruption tests |
| Real raw/production pools read identical TEXT | Three non-skipped `test_raw_and_production_pool_codecs_read_identical_text_snapshots` cases, real chain through 062, identities/counts above |
| No SQL/HTTP/queue/assessment policy change | Read-only codec/DTO source review and no production-code edits this round |
| Canonical execution authority preserved | Accepted ADR-081226-a66b, ADR-082526-7f02 and ADR-062 retirement note reviewed; no competing execution path added |
| Model materialization with `model_of`/`model_of_json`, real Run JSONB object, authorized Workspace/Project/Graph admission | UNVERIFIED by this leaf's tests; toy identity strings and tagged dictionaries prove storage, not authorization or a production caller |
| Required integration CI and genuine production reachability | NOT PROVEN: provenance fails; no production codec consumer. Full integration CI not executed in this scoped round |
| Known pre-fix / mutation failure | Not rerun in this validation-only round; no new tests or production fix claimed |

## Disposition / handoff

**BLOCKED.** No codec defect was reproduced; no production code, tests, quality
ledger, grant or gate was changed. This report is the sole changed file. No
inventory delta is needed because the test inventory did not change.

The actual blocking command is the trusted-base provenance gate, with evidence
at `quality/reachability-baseline.json:131,147` and
`quality/reachability-dispositions.json:612-613`. The permitted Vulture exception
cannot authorize these reachability rows. A separately authorized upstream
resolution or coordinated consumer integration is required; do not add fake
imports or edit candidate grants to make this slice green. This worker neither
requests nor performs production activation or GitHub mutations.

The reported `test: failure` remains UNRESOLVED without an assigned-head failing
traceback; passing focused tests is not a claim that that CI failure is repaired.
Supply that traceback before assigning a concrete test repair.

Progress: checked 1 assigned issue; done 0 repairs; skipped 0 issues; errors 1
blocking gate. Next: resolve trusted-base reachability authorization through the
proper coordinated lane and supply the exact failing CI test evidence.

