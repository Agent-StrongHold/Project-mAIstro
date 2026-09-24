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
