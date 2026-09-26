---
verified-by: maistro-repair-writer
head: c62cd7a474b3f0625fe7aeadcf995318d034a1ad
base: 8bb344e32b8693574fc0be7a93f86d941616b62c
---

# Issue #1139 repair — final re-validation at the recorded head

The previous verification pass executed its checks at `9aba8ee2a` but recorded
head `c62cd7a4` (a docs-only commit landed between the checks and the record),
so the evidence was rejected as `worktree_changed`. This pass re-executed the
battery at exactly `c62cd7a4` with a clean tree. No test was added and no
suite count moved in this pass, so there is no `inventory-delta` block.

Executed at head `c62cd7a4` (clean worktree), not trusted from any prior claim:

- `uv run ruff check .` and `ruff format --check .`: clean.
- `uv run pytest` over the touched suites (core security composition, turing
  backend auth/chat/feed/security/state, turing bridge/runtime): 130 passed.
- `uv run mypy` over all six published `src` trees: clean.
- `scripts/check-suite-inventory.py` for all three touched suites: ok.
- Diff-coverage gate reproduced with the CI-shaped producers from
  `quality.yml` (branch coverage over `maistro-core/src/maistro`,
  `maistro-turing/src/maistro_turing`, `maistro-turing/backend`):
  `check-diff-coverage.py coverage.xml --base 8bb344e3` — 11 changed non-test
  files measured, all >=90% lines / >=80% arcs, exit 0.
- Mutation guard re-run standalone:
  `test_removing_composed_http_warden_call_is_killed_by_a_literal_mutation`
  PASSED — the literal production-source mutation of `backend/security.py` is
  killed through the real `create_app()` composition.
- Live probes against `create_app()` + TestClient: hostile attacker-controlled
  mapping key and hostile nested sequence field refused 400 on `POST /v1/chat`;
  hostile service feed body refused 400 while a clean feed body passes 201;
  Warden-raising scan refuses `POST /v1/feed` with 400 (fail closed, no
  implicit allow); blocked audit entries carry
  `policy_version=warden-code-v1`, route, action, a 64-hex content hash, and
  no raw hostile detail.
- Route census re-checked against `_PROTECTED_REQUESTS`: the four
  content-bearing writes are exactly the protected set; login and GET surfaces
  are auth material / read-only, matching
  `docs/security/turing-warden-boundary.md`.
- Environment-only flake re-confirmed: `test_container_postgres::
  test_an_unreachable_server_is_an_error_not_a_fallback` fails inside the full
  core run (10087 passed) but passes standalone (61s); the diff touches no
  container code.
- No compose/CI/config/activation surface in `git diff base..HEAD`; Turing
  remains off per the activation gate, and every security import in
  `maistro-turing` resolves to `maistro.security` (no local Warden
  vocabulary, policy store, or audit authority).
