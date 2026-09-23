---
verified-by: maistro-verifier
head: 9aba8ee2a667abeae6381aa60180faa0233ba5f2
base: 8bb344e32b8693574fc0be7a93f86d941616b62c
---

# Issue #1139 — independent verification record

Executed at head `9aba8ee2a` (clean worktree), not trusted from any prior claim:

- `uv run pytest` over the PR suites (core security composition, turing backend
  auth/chat/feed/security/state, turing bridge/runtime): 130 passed.
- Focused re-run of the five load-bearing tests (mutation guard, pre-admission
  user-input refusal, model-result scan, chat audit correlation, missing-Warden
  startup failure): all PASSED individually.
- `uv run ruff check .` + `ruff format --check .`: clean. `mypy` over
  maistro-turing/src and the touched core security tree: clean.
- `scripts/check-suite-inventory.py` for all three touched suites: ok.
- `scripts/check-security-inventory.py`, `check-doc-links.py`,
  `check-deployment-claims.py`: ok.
- Diff-coverage gate reproduced with CI-shaped producers (branch coverage over
  `maistro-core`, `maistro-turing/src`, `maistro-turing/backend`): scope = all
  11 changed non-test files, exit 0. This is the gate that failed in CI at
  `2a0161b8` on `composition.py:39`; the repair commit's added refusing-arc
  test closes it.
- Live adversarial probes against `create_app()` + TestClient: hostile mapping
  key, hostile nested sequence, hostile nested admin field all refused 400
  end-to-end; Warden-raising scan on `POST /v1/feed` refuses 400 (no implicit
  allow); audit entries carry `policy_version=warden-code-v1`, route, action,
  64-hex content hash, and no raw detail; hostile chat reply never leaks.
- Route census: the four content-bearing writes (`POST /v1/chat`,
  `POST /v1/feed`, `PATCH /v1/admin/mood`, `PATCH /v1/admin/facet`) are exactly
  `_PROTECTED_REQUESTS`; login/GET surfaces are read-only or auth material,
  matching the inventory classification.
- Environment-only flake re-confirmed: `test_container_postgres::
  test_an_unreachable_server_is_an_error_not_a_fallback` fails inside the full
  core run but passes standalone (61s), and the diff touches no container code.
- No closure keywords in commit messages or the PR body ("Refs #1139" only);
  no compose/CI/config/activation surface in the diff.

Observation (not a defect): the pre-admission blocked-chat audit record hashes
the placeholder `<request blocked>` rather than the hostile payload; correlation
fields (principal/route/action/policy_version) are present and the criterion
does not require a payload digest.
