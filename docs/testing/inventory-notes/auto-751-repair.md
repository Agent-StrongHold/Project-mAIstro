---
inventory-delta:
  tests/: +1
---
# Issue #751 compliance validator repair

Adds regression coverage for a pipe-less control row and a nonexistent GitHub Actions
execution. The latter proves that a repository-owned receipt cannot make an invented
run ID support an implemented claim; the validator must inspect the canonical run.

Re-validation (2026-09-22, head 2f0a8505f): `uv run python scripts/check_compliance.py` OK
(twice, byte-identical; deterministic via the registry `as_of` snapshot),
`uv run python scripts/check-suite-inventory.py --suite tests/` OK (3534),
`uv run pytest tests/test_check_compliance.py -q` 28 passed, ruff check/format clean.
Staleness semantics exercised end to end with `--as-of 2028-01-01T00:00:00Z`
(134 findings, exit 1). No new tests in this entry; deltas unchanged.

## Repair round 2026-09-25 (head afd658c64, digest refresh)

Merged topic commits (`84d937add`, `c0f5bf794`, `f546365fa`) changed artifacts cited by
`docs/compliance/claims.json` after the 09-22 refresh, so the deterministic validator
failed with 5 stale SHA-256 digests: `ev-at-02`/`ev-govern-1`
(packages/maistro-core/tests/security/test_sentinel_policy.py), `ev-govern-2`
(packages/maistro-core/tests/security/sentinel/test_audit.py), `ev-manage-3`
(.github/workflows/ci.yml), `ev-eu-art-17` (.github/workflows/quality.yml).

Repair: recomputed the five digests against the current worktree, re-observed those
records at the new registry snapshot `as_of 2026-09-25T12:00:00Z`, and bumped
`last_verified` to 2026-09-25 for AT-02, GOVERN-1, and GOVERN-2 after actually running
their cited tests (`uv run pytest packages/maistro-core/tests/security/test_sentinel_policy.py
packages/maistro-core/tests/security/sentinel/test_audit.py -q`: 45 passed). Workflow
digests were re-observed only (no local execution is claimed for CI definitions).

Re-validation (head afd658c64 + this repair): `uv run python scripts/check_compliance.py`
OK (twice, byte-identical), `--as-of 2028-01-01T00:00:00Z` 134 findings exit 1,
`uv run pytest tests/test_check_compliance.py -q` 28 passed,
`uv run python scripts/check-suite-inventory.py --suite tests/` OK (3644, resolving the
earlier 3537-vs-3532 drift), ruff clean on tracked files. Prior findings closed: the
README now states that provider-side run retention is outside this local validator, and
the production registry carries only repository-artifact records (no self-authored
execution receipt). Untracked scratch `check_evidence_shas.py` from the timed-out prior
run is superseded by `scripts/check_compliance.py`; kept out of the commit (it alone
fails ruff), preserved at /tmp/salvage-check_evidence_shas.py. No new tests; deltas
unchanged. No CI topology change.

