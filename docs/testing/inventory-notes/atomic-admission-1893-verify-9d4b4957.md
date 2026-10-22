# atomic-admission-1893 — independent verification, job 9d4b4957

Verifier run at branch head `9ec8db66cd7e6886d80905bd870d6e5f46f346bd`
(develop base `a9fdec4cb40a62ada3e897448eabc81f2410135a`), tree clean before
and after validation; the only edit in this commit is this note.

inventory-delta:
  packages/maistro-core/tests: +0

## Executed evidence (all commands re-run by the verifier, not trusted)

- Focused leaf, no DB: `uv run pytest
  packages/maistro-core/tests/tasks/test_admission_codec.py -q` →
  128 passed, 3 skipped (skips = DSN-gated PG legs, not counted as proof).
- Disposable `pgvector:pg18` on 127.0.0.1:5599, database `adm1893_verify`
  migrated through the real chain `uv run alembic upgrade head` →
  alembic_version 066; `task_idempotency` carries the forward schema
  (TEXT request/receipt_snapshot/provenance_snapshot, smallint
  format_version, hex generation_id/claim_token). Same focused file with
  `MAISTRO_TEST_PG_DSN` + `MAISTRO_TEST_DATABASE_URL` +
  `MAISTRO_REQUIRE_PG_LEGS=1` → **131 passed, 0 skipped**;
  `task_idempotency` rows = 0 afterwards; database dropped, container removed.
- `uv run pytest packages/maistro-core/tests/tasks -q` → 654 passed.
- `uv run pytest packages/maistro-core/tests/runs -q` (with PG env) →
  1755 passed, 3 skipped.
- `uv run ruff check .` → clean; `uv run ruff format --check .` →
  3452 files already formatted.
- mypy at ci.yml argv (10 src trees) → no issues in 1092 files.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0.
- `RATCHET_BASE_REV=<base> scripts/check-reachability.py` → exit 0 (1448
  production modules, 157 unreachable; admission_identity/admission_codec
  classified inactive contract leaves, and no src module imports the codec —
  grep-verified). `check-reachability-dispositions.py` → exit 0.
- Provenance umbrellas from the base: `check-reachability-provenance.py` and
  `check-reachability-dispositions-provenance.py` → both exit 0, "no
  candidate-approved expansion" (the branch's own grants authorize nothing).
- `check-ratchet-provenance.py` → exit 0; `check-shipped-surface-truth.py` →
  exit 0; `scripts/check-suite-inventory.py` → 21 suites match (delta 0).

## Acceptance notes

- All ten prospective test names from the issue exist and assert structure
  (exact decode codes, header evidence surviving full-decode failures,
  structural header re-derivation defeating True==1/1.0==1 laundering,
  byte-preserving v2 round trip incl. tagged non-finite program_context).
- Scope: branch diff vs base touches no SQL mutation, HTTP mapping, or queue
  production code; production deltas are the new codec, the
  `maistro.runs.AdmissionAssessment` re-export, the vulture whitelist
  (scanner input only), the reachability classification, and the CI
  container repair (digest-pinned go1.27.3 rebuild for CVE-2026-111943,
  root-caused in REPAIR-NOTES-1893-0b6c5a51-container-trivy.md).
- No commit or PR text closes/fixes/resolves #1893.
- Remaining UNVERIFIED-by-design: live GitHub CI status of the
  Container scan + SBOM + cosign job at this head (only a CI run can prove
  it); the local Trivy root cause and repair are verified on the Dockerfile
  level only.
- Cosmetic: the two `ratchet-authorizations.json` grant reasons still say the
  modules are "dispositioned CONNECT (group runs-root-admission-contracts)"
  in `quality/reachability-dispositions.json`, which contains no such group —
  stale prose in a reason field; no gate consumes it and the grants authorize
  nothing (umbrellas pass from the base without them).
