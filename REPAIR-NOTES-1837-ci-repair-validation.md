# REPAIR-NOTES-1837-ci-repair-validation

Lane L1837 repair round: focused validation at head 26879956a.

Validation run:
- uv sync --locked --extra dev: OK
- ruff check .: OK (all checks passed)
- ruff format --check .: OK (3529 files already formatted)
- mypy (CI package list): OK (942 files)
- check-suite-inventory.py: OK (21 suites)
- check-vulture-baseline.py (packages/*/src, min-confidence 60): OK (1263 == 1263)
- check-radon-baseline.py: OK (127 == 127)
- check-promotion-surface.py: OK
- check-reachability-dispositions.py: OK
- check_direct_effects.py: OK (53 sites dispositioned)
- check-adr-status-language.py: OK
- check-adr-index.py: OK
- check-backlog-consistency.py: OK
- check-merge-markers.py: OK
- check-doc-links.py: OK
- check-branch-independence.py: OK
- check-contract-markers.py: OK
- check-convergence-matrix.py: OK
- check-citation-status.py: OK
- pytest root tests/: 5802 passed, 139 skipped
- pytest packages/maistro-server/tests: 646 passed, 10 skipped
- pytest packages/maistro-turing/design/ext-sdk/ext-harness: 1307 passed, 1 skipped
- pytest packages/maistro-core/tests: 16740 passed, 1213 skipped, 7 xfailed
- pytest packages/maistro-canvas/bootstrap/registry: 925 passed, 76 skipped
- pytest packages/maistro-evolve/rsi: 2791 passed, 8 skipped, 1 failed (env/image: maistro-builders:latest has no pytest module; docker-gated test_real_container_runs_the_vector_and_returns_its_status; unrelated to #1837)
- pytest packages/hive-conductor/backend/tests: 4062 passed, 29 skipped

Residual risk / open gate:
- ADR-101826-c3f1 remains Proposed; owner acceptance by @BlakeMatthews-dev (or designated reviewer) is a human decision gate per #1837 and is UNVERIFIED. No code change can resolve it.
- The rsi contained-fitness failure is an environment/image toolchain gap, not a repository regression; the builders image lacks pytest. Not in scope for this decision gate.
