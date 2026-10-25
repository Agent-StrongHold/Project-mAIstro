---
inventory-delta:
  packages/maistro-core/tests: 0
---

# Issue #1893 repair revalidation — 26310082

## Frozen scope and disposition

Only issue #1893, branch `auto-1893`, starting source
`4e8a84c77db53588f2fb602764f8a150d03cee89`, assigned develop base
`af799688335f9a7dba7999a05e0e13f102c6c5ae`. Initial worktree clean.
Frozen candidate write set: admission codec, its tests, this note, and the
vulture ledger only if the required scan identified justified amendments.
**Actual change: this note only. No source/test/ledger changes warranted.**

**BLOCKED.** The reported bound encode defect is already repaired:
`admission_codec.py:290` writes the existing binding receipt as `task_id`.
Fresh real PostgreSQL tests prove compatibility with migration 055. Vulture
passes, with no unbanked or removed identities to amend. The reproduced gate
failure is trusted-base reachability/disposition authorization for the two
inactive modules, outside the vulture-only repair exception. No fake callers,
grants, gate changes, activation, GitHub mutations, or discarded work.

Read repository instructions, supplied dispatch issue/PR evidence, prior result
artifact and all five driver logs. Driver focused result (201 passed, 3 skipped)
was not treated as DB evidence. Accepted ADRs 081426-1f7c, 082526-7f02,
082826-b601 and 082826-d9f5 retain immutable admission provenance and the single
`Goal -> Graph -> Run -> NodeRun -> Attempt` execution/store/consumer model.
Local repair ownership is assumed from the explicit lane assignment, not an
independent activation or integration authorization. No ADR conflict introduced.
A guessed ADR filename was not found and skipped; the actual b601 document was
then located/read. Captured-evidence extraction initially failed on a list/dict
shape assumption, then succeeded. Docker daemon unavailable; local PG used.

## Executed validation

All commands ran against the exact starting source above. Logs, collected
node IDs and JUnit properties are retained in
`/home/dev/maistro/jobs/2631008251b9426db06c4c783b8dc168/`.

- `uv sync --locked --extra dev`: passed.
- Created dedicated disposable PostgreSQL **18.6** DB
  `maistro_1893_26310082`. `DATABASE_URL=postgresql:///maistro_1893_26310082
  uv run alembic upgrade head`: passed, real empty-to-head chain through
  **060**, including **055** (`repair-migrate.log`). No downgrade or SQLite
  recreation used as durability proof.
- Both `MAISTRO_TEST_PG_DSN` and `MAISTRO_TEST_DATABASE_URL` set to
  `postgresql:///maistro_1893_26310082`, `MAISTRO_REQUIRE_PG_LEGS=1`:
  `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py
  packages/maistro-core/tests/runs/test_root_admission_identity.py -x -q
  -o junit_family=legacy --junitxml=<job>/repair-focused-pg.xml`:
  **204 passed, no skips** (`repair-focused-pg.log`). Raw/production backend
  PID pairs (production first), same database over local socket: unbound
  **2733940/2733941**, bound **2733942/2733943**, acknowledged
  **2733944/2733945**. Each verifies exactly **one persisted scoped row**,
  identical TEXT mappings and complete DTOs, plus typed failure for escaped
  surrogate evidence in all snapshots. Each cleans up its row. Final SQL:
  revision **060**, admission rows / distinct generations / distinct bound
  Run IDs **0 / 0 / 0** (`repair-final-sql.log`).
- Process-local mutation of the encoder forcing `task_id=None` while retaining
  `run_id`, via `uv run python` invoking `pytest.main` with
  `-q -k test_v2_round_trip_preserves_all_snapshot_bytes`: **2 failed, 1 passed,
  128 deselected**. Both failures are the independent storage assertion at
  `test_admission_codec.py:134` (`repair-binding-mutation.log`). This proves
  existing regression sensitivity, not a new source defect. No file mutation.
- `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 uv run pytest
  packages/maistro-core/tests -x -q`: **14623 passed, 986 skipped, 1 xfailed,
  53 warnings** in 211.39s (`repair-core-tests.log`). No DB env in this broader
  run; skips are not durability proof. Warnings include aiosqlite callbacks
  after loop closure and an unawaited fake-process coroutine. The reported
  hosted `test` failure was not reproduced in the changed package.
- Focused `--collect-only -q`: **204 nodes** (`repair-focused-nodes.log`).
  `uv run python scripts/check-suite-inventory.py --suite
  packages/maistro-core/tests`: passed, **15610 nodes**, zero duplicate evidence
  (`repair-inventory.log`). No tests added or removed this round.
- `uv run ruff check .`: passed. `uv run ruff format --check .`: passed,
  **3166 files**. `uv run mypy
  packages/maistro-core/src/maistro/tasks/admission_codec.py
  packages/maistro-core/src/maistro/runs/admission_identity.py`: passed.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: passed, **1328 reviewed
  identities / 1328 findings** (`repair-vulture.log`). No ledger edit justified.
- `uv run python scripts/check-<name>.py` for `reachability`,
  `reachability-dispositions`, `promotion-surface`, `shipped-surface-truth`:
  all passed (individual `repair-<name>.log` files). Candidate-local passes do
  not authorize debt relative to the trusted base.
- `RATCHET_BASE_REV=af799688335f9a7dba7999a05e0e13f102c6c5ae uv run python
  scripts/check-ratchet-provenance.py`: **FAILED**, exit 1
  (`repair-provenance.log:17-32`): NEW unauthorized unreachable modules and
  dispositions for `maistro.runs.admission_identity` and
  `maistro.tasks.admission_codec`. Candidate ledger edits cannot approve them.

## Acceptance accounting and residual risks

All ten named prospective contracts executed in the 204-test focused run:

| Criterion | Executed evidence |
| --- | --- |
| v2 snapshot bytes and immutable DTOs | `test_v2_round_trip_preserves_all_snapshot_bytes`, all three states |
| owner UUID hex at storage only | `test_owner_token_is_hex_at_storage_only` and UUID/corruption cases |
| bound/unbound/partial legacy distinction | `test_legacy_binding_unbound_and_partial_are_distinct`, receipt-only and missing-receipt cases |
| expired header invents no identity | `test_expired_legacy_header_does_not_invent_missing_identity` |
| malformed snapshot preserves expiry | `test_header_preserves_expiry_even_when_legacy_snapshot_decode_fails` |
| partial binding preserves fingerprint | `test_header_preserves_fingerprint_even_when_legacy_binding_is_partial` |
| unknown format fails closed | `test_unknown_format_cannot_be_reinterpreted_as_legacy` |
| tagged nonfinite evidence/fingerprint preserved | `test_tagged_nonfinite_snapshots_round_trip_without_fingerprint_change` |
| invalid/duplicate/nonobject/bare nonfinite JSON rejected | `test_invalid_and_duplicate_json_is_rejected` plus nesting/precision/Unicode cases |
| raw and production pool TEXT parity | `test_raw_and_production_pool_codecs_read_identical_text_snapshots`, all three real migrated PG states |

Signed scalar validation, header mismatch, missing columns, fresh flat mappings
and safe typed errors also run in that suite. Source inspection verifies no
clock, incoming fingerprint, SQL mutation, HTTP mapping or queue change.
Legacy bound pairs without receipt evidence remain explicit typed failures;
no receipt identity is invented to fit the #1851 DTO constructor.

These are codec/storage proofs, **not reachable admission-service proofs**.
`admission_codec.py:51` explicitly states there is no production consumer, and
source search confirms no runtime importer. The PG fixture uses synthetic
identity strings, not authorized Workspace/Project/registered Graph admission.
Reachable authorized admission, actual `model_of`/`model_of_json`
materialization, Run JSONB object insertion, live expiry/409 ordering, full
required hosted CI and production activation remain **UNVERIFIED**.
Constructor-side normalization before encoding is not certified by this codec
storage test. The captured PR-head checks show `exact-debt-ledger` failure
without summary/traceback; no actionable hosted `test` traceback was supplied.
That test failure is **UNRESOLVED**, not guessed into a cosmetic repair.

Next: owner-coordinated trusted integration base/consumer resolution for the
staged leaves, and actual failing hosted `test` traceback if distinct from
provenance. Repeating vulture banking cannot repair the reproduced blocker.
Progress: checked **1**, done **0** source repairs (revalidation complete),
skipped **0** issues, errors **1** reproduced gate failure. Handoff committed
locally; no merge or activation approval asserted.
