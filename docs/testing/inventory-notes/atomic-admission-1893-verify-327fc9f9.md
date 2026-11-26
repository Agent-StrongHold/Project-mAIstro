---
inventory-delta:
  packages/maistro-core/tests: 0
---

# #1893 verification round at 94de9c2ec (job 327fc9f95ad44d138ec3c5e7fdab7ea5)

Snapshot: issue #1893 only; branch `auto-1893`, starting head verified exactly
`94de9c2eccc020f426da16dfcaeef6ff815dbdea`, base `ab8b3737fa64`. Worktree clean
at entry, no incoming uncommitted work to salvage. Docs-only change this round
(this note); no source, test, ledger, grant, gate or migration edits. No
GitHub mutations.

## exact-debt-ledger at CI argv (the one red job at this head, run 39053675872)

Environment: `uv sync --locked --all-extras` re-applied first (the driver's
check-0 had dropped `maistro-bootstrap`/`playwright`/`pyee`).

- Step `check-shipped-surface-truth.py` → exit 0 ("matrix is complete").
- Step `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` → exit 0, **1322 reviewed identities → 1322
  findings, unclassified 0, never_allowlist 0**. The brief's ledger-amendment
  path has no target: there is nothing to add and nothing to remove.
- Step `check-ratchet-provenance.py` with `RATCHET_BASE_REV=origin/develop`
  (the pull_request shape, PR base = develop) → exit 1 on **exactly**
  `maistro.runs.admission_identity` + `maistro.tasks.admission_codec`
  (reachability + reachability-dispositions); all eight other ratchets OK.
- Live `git fetch origin`; `refs/remotes/origin/develop` = `ab8b3737fa64` =
  merge base, 0 behind. The #1893 reachability grants exist on this branch
  (commit `6af21c54e`, an ancestor of HEAD, +10 lines in
  `quality/ratchet-authorizations.json`, owner `@BlakeMatthews-dev`, issue
  `#1893`) and are absent on develop — the branch-vs-develop grant file diff
  is exactly those two rows.
- **Grant-first proof (this round)**: `RATCHET_BASE_REV=6af21c54e` (the grant
  commit is in HEAD's ancestry, so `_merge_base` reads the trusted ledgers
  from it) → the FULL provenance gate exits **0** ("171 unreachable module(s)
  have dispositions; new debt uses prior reachability authorization"; all
  ratchets OK). Mechanism re-read in source:
  `scripts/ratchet_provenance.py:478` `load_authorizations` resolves grants
  from the merge base only, and its docstring states the two-merge
  consequence verbatim. Sole remaining ingredient is the owner-side grant
  landing on develop; no legitimate in-branch repair exists (wiring and
  candidate-side ledger reads are both forbidden).

## B2 acceptance re-proven live (this round, fresh disposable DB)

`pgvector/pgvector:pg18` container `adm1893-r2` (removed after the round);
`uv run alembic upgrade head` ran the real chain 001→063 (69 "Running
upgrade" lines, exit 0) against `adm1893_r2`. With
`MAISTRO_TEST_PG_DSN`/`MAISTRO_TEST_DATABASE_URL` on that same DB and
`MAISTRO_REQUIRE_PG_LEGS=1` (skips become failures):

- `uv run pytest packages/maistro-core/tests/tasks/test_admission_codec.py -q`
  → **131 passed, 0 skipped** (exit 0). One harness DSN artifact on the way:
  passing the SQLAlchemy `postgresql+asyncpg://` form as `MAISTRO_TEST_PG_DSN`
  errors at asyncpg pool setup (the env var goes straight to
  `asyncpg.create_pool`, `packages/maistro-core/tests/conftest.py:175`); the
  plain `postgresql://` form is the contract, matching the docstring at
  `test_admission_codec.py:455-462`.
- codec + identity together → **204 passed, 0 skipped** (exit 0).

Without DSNs: the focused file gives 128 passed, 3 skipped; the skips are the
DSN-gated `test_raw_and_production_pool_codecs_read_identical_text_snapshots`
legs at `test_admission_codec.py:470`, not fake passes.

## Issue-conformance spot checks (source read, this round)

- `packages/maistro-core/src/maistro/tasks/admission_codec.py`: exact public
  surface present — `AdmissionDecodeCode(StrEnum)` with all six values
  (:127-135), `AdmissionRowDecodeError(ValueError)` carrying `code` +
  validated-hash `scope_key` (:138-148), `@dataclass(frozen=True, slots=True)
  AdmissionRowHeader` with exactly the six specified fields (:157-172),
  `decode_admission_header` (:207), `decode_admission_record` (:233),
  `encode_admission_record` (:260). 25 `from None` suppressed re-raises.
- All 10 prospective tests present by name in
  `packages/maistro-core/tests/tasks/test_admission_codec.py` (1 def each).
- No production wiring: `grep -rn admission_codec packages/*/src` matches only
  the module itself and `_vulture_whitelist.py` (scanner input).
- Net non-docs diff vs develop remains: `admission_codec.py` (new),
  `admission_identity.py` (new, #1851 prerequisite absent on develop),
  `_vulture_whitelist.py` (M), four test files (2 new, 2 M), and the three
  quality ledgers. Zero changes to `.github/`, `scripts/`, `alembic/`.

## Types and lint (this round)

- mypy at the CI `test`-job argv (`.github/workflows/ci.yml:118-127`, all ten
  package src dirs) → **Success: no issues found in 1059 source files**.
- `uv run ruff check .` → "All checks passed!"; `uv run ruff format --check .`
  → "3301 files already formatted".

## Handoff (single owner action, outside lane authority)

Unchanged from the prior rounds: land `6af21c54e`'s
`quality/ratchet-authorizations.json` rows on develop (grant-first, two-merge
rule), then re-evaluate this branch — the grant-first proof above shows all
three exact-debt-ledger steps green with the branch content unchanged.
