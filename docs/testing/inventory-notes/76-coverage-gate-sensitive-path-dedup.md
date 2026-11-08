# Issue 76 repair round — coverage (no services) gate

## Failure

`coverage (no services)` (quality.yml `coverage-unit`) failed on the
maistro-rsi leg:
`packages/maistro-rsi/tests/test_sensitive_paths.py::TestItStaysASurfaceAndNotAWildcard::test_the_patterns_are_unique`
asserted 92 unique patterns in a 93-entry `SENSITIVE_PATH_PATTERNS`.

Root cause: this branch (5bd2eee1c) and develop (09d56b6a0, #2263) each added
`"maistro/sandbox/"` to the same tuple in different sections; the develop-sync
merge (ed45aced8) concatenated both entries silently. Containment behavior was
unchanged (the pattern is the same string); only the uniqueness invariant
pinned in #2143 observed the duplication.

## Repair

Removed the branch-side duplicate entry and folded its #76 rationale into a
comment pointing at the surviving entry in the convergence-closure
enumeration (`packages/maistro-rsi/src/maistro_rsi/sensitive_paths.py`).
No test moved, so this note records no inventory delta.

## Reproduction and evidence

Revision ed45aced82ca + this fix, local WSL workspace (bwrap 0.11.1 with
userns namespaces available; docker 29.1.3 with python:3.12-slim pre-pulled),
CI's exact `coverage-unit` environment (`REQUIRE_AUTH=false`,
`MAISTRO_DRY_RUN=1`, workspace-src PYTHONPATH, `--timeout=30 -q`,
`coverage run --branch` per publish-set package):

- maistro-bootstrap/tests: 264 passed, 1 skipped
- maistro-evolve/tests: 1000 passed, 6 skipped
- maistro-rsi/tests: before fix 1 failed / 1794 passed; after fix 1795 passed, 2 skipped
- maistro-core/tests: 16791 passed, 1213 skipped, 7 xfailed
- maistro-canvas/tests: 581 passed, 75 skipped

Post-fix gates re-run locally: `ruff check .` (clean), `ruff format --check .`
(3536 files formatted), `scripts/check-vulture-baseline.py packages/*/src
--min-confidence 60 --exclude '*/third_party/*'` (exit 0; 1256 reviewed
identities, all banked), `scripts/check-promotion-surface.py` (ok),
`scripts/check-suite-inventory.py --suite packages/maistro-rsi/tests` (ok,
counts unchanged).
