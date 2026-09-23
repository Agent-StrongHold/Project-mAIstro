---
inventory-delta:
  packages/hive-conductor/backend/tests: +3
---

Adds three focused Conductor transport tests. The dashboard screenshot route is
verified to attach `BrowserNetworkGuard` before its fixed localhost navigation,
the UI hill-climber screenshot path is verified to abort a loopback URL before
the fake wire is reached, and the reachable Hyperlight hill-climb workload is
verified to use the shared sync HTTP client and guard every sync browser context
it creates. The shared maistro-core browser
suite already covers explicit browse, autonomous search/model navigation,
subresources, and redirect-to-private behavior at the real Playwright route
boundary.

Independent verification record (L155, head ecc853f7d, 2026-09-23)
------------------------------------------------------------------

Executed on this head, not inferred:

- `uv run pytest packages/maistro-core/tests/tools/browser/test_client.py
  packages/maistro-core/tests/tools/browser/test_net_guard.py -q` → 127 passed.
- `.venv/bin/python -m pytest
  packages/maistro-core/tests/tools/browser/test_playwright_transport.py -q`
  → 4 passed (playwright 1.63.0 + cached Chromium installed; real route API,
  real HTTP servers, private server asserted to receive zero requests).
- `.venv/bin/python -m pytest
  packages/hive-conductor/backend/tests/test_browser_network_policy.py
  packages/hive-conductor/backend/tests/test_engine_service.py -q` → 38 passed.
- `uv run pytest packages/maistro-core/tests/security/test_ssrf.py
  packages/maistro-core/tests/security/test_outbound_policy.py -q` → 141
  passed (ordinary HTTP seam intact).
- Gates: `ruff check .`, `ruff format --check .`,
  `check-security-inventory.py`, `check-model-egress.py`,
  `check_direct_effects.py`, `verify-monorepo-layout.sh`,
  `check-suite-inventory.py` (both suites) — all pass.
- Transport census re-derived independently: the repo's only production
  Playwright entry points are `tools/browser/client.py`,
  `backend/services/ui_auto_climb.py`, `backend/routes/widgets.py`,
  `run_hill_climb.py`, and `hill-climb-ui.sh` (dispatched as the Hyperlight
  workload by `backend/services/ui_climb_vm.py`); `browser_use` is imported
  only by `tools/browser/client.py`. All five attach a guard before any page
  exists, and all five are named in SECURITY.md's browser transport row.

Known non-green gates on this head, measured inherited from the develop base
(8bb344e32), not introduced by this change:

- `check-vulture-baseline.py` exits 1 with repo-wide ledger drift; the vulture
  ledger is byte-identical between base and head, and none of the branch's 19
  changed files appear in the failure output.
- `check-ac-state.py --run-tests --ratchet --mandate 3e9f7525…` exits 1 on
  design_coverage 33.0281 < 33.9095 floor; a `git archive` of the base commit
  measures the identical 33.0281. The per-change mandate (22 criteria claimed,
  0 unproven) and chain mandate pass.
- `test_log_redaction.py::test_install_is_idempotent` fails identically on the
  base commit (environment-dependent, pre-existing).
