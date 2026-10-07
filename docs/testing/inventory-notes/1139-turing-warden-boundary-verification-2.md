---
verified-by: maistro-verifier
head: 47ed4b4a5e0a26269bd244456f615c6e0fb9dd11
base: 8bb344e32b8693574fc0be7a93f86d941616b62c
---

# Issue #1139 independent verify pass at head 47ed4b4a

Re-derivation of the acceptance criteria at the exact PR head (47ed4b4a),
worktree clean before this note. None of the prior verify/repair claims were
trusted; each item below names what was executed in this session.

Executed at head `47ed4b4a`:

- Driver-deterministic checks re-run: `uv run ruff check .` (clean),
  `ruff format --check .` (2531 files already formatted), pytest over the exact
  PR file list (`test_composition.py`, backend `conftest/test_auth/test_chat/
  test_feed/test_security/test_state`, `tests/test_bridge.py`,
  `tests/test_runtime.py`) = **130 passed**, `check-suite-inventory.py` for
  core / turing backend / turing suites = ok x3.
- Canonical `uv run mypy packages/maistro-core/src packages/maistro-server/src
  packages/maistro-turing/src packages/maistro-canvas/src
  packages/maistro-bootstrap/src packages/maistro-registry/src`:
  Success, no issues in 713 files. (An ad-hoc path set that omits
  `maistro-bootstrap/src` reports import-not-found noise; the AGENTS.md
  command is the canonical one and is clean.)
- Diff-coverage gate reproduced end-to-end with the CI-shaped producers from
  `quality.yml` (`coverage run --branch` for `maistro-core/src/maistro` via
  full core tests, `maistro-turing/src/maistro_turing`,
  `maistro-turing/backend`; `coverage xml`):
  `check-diff-coverage.py coverage.xml --base 8bb344e3` -> 11 measured /
  9 exempt, all files >=90% lines / >=80% branches, exit 0. The prior CI
  coverage-gate failure at `2a0161b8` does not reproduce (commit `9aba8ee2a`,
  which added the measured coverage, postdates it).
- `check-deployment-claims.py` -> OK, exit 0. Diff touches only `docs/` and
  `packages/`; no activation/composition change, Turing remains gated by
  ADR-081426-fb9f.
- Closure-keyword review: PR #1444 body contains only "Refs #1139"; no
  fixes/closes/resolves in the PR body or any commit message in
  `8bb344e3..47ed4b4a`.

Acceptance re-derived from source and live execution:

- Route census (`@router` across backend/routes) = exactly the four
  content-bearing routes listed in `_PROTECTED_REQUESTS`
  (POST /v1/chat, POST /v1/feed, PATCH /v1/admin/mood, PATCH /v1/admin/facet);
  login/GET/read-only routes correctly classified not-applicable; matches
  `docs/security/turing-warden-boundary.md`.
- Middleware is production wiring, not test-only: added inside `create_app()`
  with `app = create_app()` at module scope; auth middleware is outermost so
  identity precedes the scan.
- Live adversarial probe through the real `create_app()` composition
  (TestClient, no test fixtures): hostile mapping key on PATCH /v1/admin/mood
  -> 400 "request refused by Warden"; hostile nested value on
  PATCH /v1/admin/facet -> 400; clean admin mood -> 200; GET /v1/feed
  (non-applicable) -> 200. Audit records for those requests carried
  principal/route/action/policy_version (`warden-code-v1`)/sha256/length and
  contained no raw content (asserted programmatically).
- Named guard tests observed passing in the 130-test run: startup fail-closed
  pair, warden-unavailable refusal, blocked-chat-with-failing-audit-sink,
  user-input refusal before canonical admission (provider asserted uncalled),
  model-result scan with FAILED-run-correlated `turing.tool_result` audit,
  chat audit correlated to the canonical Run, and the literal-mutation guard
  `test_removing_composed_http_warden_call_is_killed_by_a_literal_mutation`
  (production-source mutation driven through real `create_app()` in a
  subprocess).

Pre-existing, out-of-scope observation (new):

- `packages/maistro-core/tests/test_container_postgres.py::
  test_an_unreachable_server_is_an_error_not_a_fallback` failed once during
  the full core-suite coverage producer run (1 failed / 10087 passed) and
  passes in isolation (it is a ~61s unreachable-server timing test). The
  #1139 diff touches no PostgreSQL/container code, and the driver's
  deterministic checks for this job are green; recorded as an environment
  flake for its owner, not a regression of this change.
