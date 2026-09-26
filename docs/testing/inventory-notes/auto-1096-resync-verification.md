---
inventory-delta:
  tests/: +0
---

# auto-1096-resync-verification

Independent verification round at head `7e487817` — the branch resynced onto
develop base `031bd074` (HEAD is that merge; worktree clean, `git status`
empty, no merge in progress). `scripts/check-merge-markers.py`: ok, no
conflict markers in any tracked file, so the carried-over develop-sync block
is resolved at this head.

Re-executed at `7e487817` (all exit 0):

- `uv run pytest` over the five-package suites (bootstrap x4, design,
  registry, rsi x2): **115 passed**.
- `uv run pytest tests/test_adr102_sibling_ssrf_seam.py
  tests/test_check_security_inventory.py tests/test_http_client_sites.py
  tests/test_check_adr_index.py tests/test_check_diff_coverage.py
  tests/test_check_cross_package_imports.py`: **137 passed**.
- `uv run ruff check .`; `scripts/check-security-inventory.py` (59 cited
  paths, 23 inventory rows, 2 counted claims recomputed);
  `scripts/check-cross-package-imports.py` (2591 files);
  `scripts/check-suite-inventory.py` (14 suites).
- Coverage-gate reproduction with the full producer chain: root `tests/`
  under `coverage run --branch --source=scripts` (3667 passed, 100 skipped)
  plus evolve/rsi/bootstrap/design/registry/hive-conductor producers →
  `scripts/check-diff-coverage.py coverage.xml --base 031bd074`: **13
  measured files pass 90% lines / 80% branches, 13 test-exempt, exit 0**.

Independent AST census (not the gate): zero `httpx.Client/AsyncClient`
constructions outside `maistro/http.py` in non-test production code; the only
constructor hit is the documented `hive-conductor/backend/routes/containers.py`
Unix-socket exemption. Residual `httpx.get/post` convenience calls in
hive-conductor backend routes, `maistro-canvas/frontend/server/mcp/`, and
`scripts/openrouter_rpm_pacer.py` pre-exist on the base (untouched by this
branch) and sit outside the five-package sibling census; they are convenience
calls, not the module-level constructors the ADR-102 census criterion names.

Remote CI at `7e487817`: **Coverage gate (publish-set floor + diff coverage)
= pass (15m32s)** — the gate that failed at `0525645b` is green at this head;
30 checks pass. `test` and the `gates-ran` aggregate were still pending at
snapshot time and remain UNVERIFIED from this lane. PR body and every commit
message on the branch say "Refs #1096"; no `fixes/closes/resolves` keyword.
