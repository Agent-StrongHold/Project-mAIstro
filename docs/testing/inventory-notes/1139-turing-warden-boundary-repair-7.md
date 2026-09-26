---
verified-by: maistro-repair-writer
head: 0cd0ce5aa624a4cae99612f1858114591b747bba
base: 8bb344e32b8693574fc0be7a93f86d941616b62c
---

# Issue #1139 repair — independent re-validation at head 0cd0ce5a

This pass re-executed the validation battery at exactly `0cd0ce5a` on a clean
tree and independently re-derived the acceptance evidence instead of trusting
the prior verify record. No test was added and no suite count moved, so there
is no `inventory-delta` block.

Executed at head `0cd0ce5a` (clean worktree):

- `uv run ruff check .` / `uv run ruff format --check .`: clean.
- `uv run pytest packages/maistro-core/tests/security/test_composition.py
  packages/maistro-turing/backend/tests/ packages/maistro-turing/tests/`:
  261 passed (wider scope than the prior 130-test pass — full turing backend
  and turing src directories, not a selected file list).
- `uv run mypy` over all six published `src` trees: clean (713 files).
- `scripts/check-suite-inventory.py` for core, turing backend, and turing src
  suites: ok. `scripts/check-deployment-claims.py`: ok.
- Diff-coverage gate reproduced end-to-end with the CI-shaped producers from
  `quality.yml` (`coverage run --branch` over `maistro-core/src/maistro`,
  `maistro-turing/src/maistro_turing`, `maistro-turing/backend`; `coverage
  xml`): `check-diff-coverage.py coverage.xml --base 8bb344e3` — 11 changed
  non-test files measured, 9 test files exempt, all measured files >=90% lines
  / >=80% branch arcs, exit 0. The recorded CI coverage-gate failure at
  `2a0161b8` therefore does not reproduce at this head; the coverage-adding
  commit `9aba8ee2a` postdates `2a0161b8`.
- Acceptance spot-checks re-derived from source, not from prior claims:
  canonical imports only (`maistro.security.*`) in `maistro-turing`;
  `_PROTECTED_REQUESTS` covers exactly the four content-bearing routes from a
  fresh `@router` census and matches
  `docs/security/turing-warden-boundary.md`; the pre-Run unrecorded-reply
  fallback is gone (admission failure refuses 503); `get_state()` /
  `get_execution_plane()` refuse when never composed; runtime audit requires a
  canonical Run and resolves principal/Workspace/Project from it.
- Named evidence tests re-run verbose and PASSED: startup fail-closed pair,
  warden-failure refusal, blocked-chat-with-failing-audit-sink, nested/mapping
  payload scans, user-input refusal before canonical admission (provider
  asserted not called), model-result scan before return/memory with
  FAILED-run-correlated audit (`action=turing.tool_result`, `policy_version`),
  chat audit correlated to the canonical Run, and the literal-mutation guard
  `test_removing_composed_http_warden_call_is_killed_by_a_literal_mutation`
  through the real `create_app()`.

New pre-existing failure found and scoped OUT of this issue:

- `packages/maistro-core/tests/security/test_log_redaction.py::
  test_install_is_idempotent` fails under pytest's logging plugin (two
  unredacted handlers appear on the fixture logger); it passes with
  `-p no:logging`, passes in a bare-python probe of the same calls, and fails
  identically on `develop@622eaf7ca` in the canonical clone, which does not
  contain any of the #1139 diff (file last touched by the initial release).
  Environment/plugin interaction, not caused by this change; recorded here so
  the reporting lane can route it to its owner.
