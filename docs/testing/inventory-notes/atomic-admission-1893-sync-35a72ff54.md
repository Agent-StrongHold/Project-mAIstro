---
inventory-delta:
  packages/maistro-core/tests: +0
---
# atomic-admission-1893 — develop sync to 35a72ff54, round-3 exact-debt-ledger re-validation

Round: repair lane L1893, job 4ab87d5af0cd48338410f37a3403abbc, branch auto-1893.

## What moved

`origin/develop` advanced from the previously synced `eec7a587039` to
`35a72ff54` (4 commits: #2183 bootstrap runtime, #2201 engine-image canvas
deps, #2196 boto3 bump, #2188 pylint bump). Merged `refs/remotes/origin/develop`
into auto-1893 as merge `3f719990c`, conflict-free.

## Ledger integrity after the merge

Per the quality-merge hazard, quality/ rows were diffed before/after:

- `git diff --numstat 3efff5983 -- quality/` shows exactly one changed file:
  `quality/image-inventory.json` (2/2) — verified byte-identical to develop's
  tip content (`git diff refs/remotes/origin/develop -- quality/image-inventory.json`
  is empty), i.e. develop's own change absorbed, not a row loss.
- Branch vs develop stays purely additive: 10 lines `ratchet-authorizations.json`
  (the two #1893 grants), 2 `reachability-baseline.json`,
  11 `reachability-dispositions.json`. Zero deletions.

## exact-debt-ledger at CI argv on merged head 3f719990c

All three steps of `.github/workflows/vulture-ratchet.yml::exact-debt-ledger`
re-run at exact argv with `RATCHET_BASE_REV=origin/develop`:

- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'`
  → exit 0, exact 1322==1322 against base 35a72ff54. Zero unbanked identities,
  so the round brief's "amend quality/vulture-baseline.json" still has no target.
- `check-shipped-surface-truth.py` → exit 0.
- `check-ratchet-provenance.py` (umbrella) → exit 1, failing only on the two
  delegated adapters, on exactly `maistro.runs.admission_identity` +
  `maistro.tasks.admission_codec` ("NEW disposition absent from trusted ledger
  and not covered by an already-landed reachability authorization").

Grant-first proof re-run on the merged tree: `RATCHET_BASE_REV=6af21c54e`
makes the full umbrella exit 0 (53 consumers, all ratchets OK). Fresh
owner-state check: `git merge-base --is-ancestor 6af21c54e refs/remotes/origin/develop`
is false — develop tip 35a72ff54 still does not carry the grant, and none of
the 4 new develop commits touches `quality/ratchet-authorizations.json`.
Sole remaining ingredient is therefore unchanged: the owner-side grant-first
landing on develop (two-merge rule, `load_authorizations` reads base-only).

## Battery on merged head 3f719990c

- `uv sync --locked --extra dev` (develop bumped uv.lock: boto3/botocore 1.43.114) OK.
- `uv run ruff check .` OK; `uv run ruff format --check .` OK (3329 files).
- Focused `pytest packages/maistro-core/tests/tasks/test_admission_codec.py -q`
  → 128 passed, 3 skipped (skips are the DSN-gated PG legs at
  test_admission_codec.py:470). Driver five-file battery (cli_lock,
  pack_contracts, root_admission_identity, admission_codec) → 346 passed,
  3 skipped.
- mypy at ci.yml argv (10 src trees) → Success, 1063 source files.
- `check-suite-inventory.py` (all suites) → 17/17 OK, 32101 unique node IDs;
  maistro-core 16670 matches the recorded baseline (this round adds no tests,
  inventory delta +0; develop's own new root tests carried their notes).
- PG durability re-proven LIVE on fresh pgvector:pg18 DB `adm1893_r7`
  (127.0.0.1:18766, container auto-1893-pg-r7) through the real alembic chain
  (`DATABASE_URL=… uv run alembic upgrade head`, head 063; `task_idempotency`
  carries the forward schema: scope_key/claim_token/fingerprint TEXT,
  format_version smallint, generation_id TEXT, bigint scalars, TEXT
  snapshots, acknowledged_at, legacy completed_at) with
  `MAISTRO_REQUIRE_PG_LEGS=1`: codec + identity suites → **204 passed,
  0 skipped**. DB dropped and container removed after the run.

## Issue acceptance re-check (#1893 B2)

- Exact interfaces present in `maistro/tasks/admission_codec.py`:
  `AdmissionRowHeader` frozen+slots (6 fields, `format_version: Literal[1, 2]`),
  `decode_admission_header`, `decode_admission_record(row, *, header)`
  (structural header-vs-row re-derivation, mismatch → `invalid_header`),
  `encode_admission_record` (fresh flat mapping, `.hex` at storage only),
  `AdmissionDecodeCode` (all six values), `AdmissionRowDecodeError(ValueError)`
  with `code` + validated-hex-only `scope_key`; 25 `from None` raisers
  suppress unsafe chains.
- All 10 prospective tests from the issue are present and passing (plus 60
  further cases); receipt-only and announced-without-Run yield
  `partial_legacy_binding`, never an inferred identity.
- No SQL mutation, HTTP mapping or queue change: branch delta vs develop is
  exactly the two contract modules, `_vulture_whitelist.py` (scanner input,
  not shipped) and tests.
- Decoder takes no clock or incoming fingerprint; implements no assessment or
  claim decision (signatures verified in source).
