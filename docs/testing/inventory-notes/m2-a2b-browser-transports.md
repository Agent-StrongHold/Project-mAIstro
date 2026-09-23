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

Repair-phase re-verification (L155, head 918c1ff38, 2026-09-23)
---------------------------------------------------------------

Every claim above was re-executed on this head rather than carried forward:

- browser client + net guard: 127 passed; real-Chromium transport: 4 passed;
  Conductor browser policy + engine service: 38 passed; `test_ssrf.py` +
  `test_outbound_policy.py`: 141 passed; `test_transport.py`: 32 passed.
- `ruff check .`, `ruff format --check .`, `check-security-inventory.py`,
  `check-model-egress.py` (which also runs `check_direct_effects.py`), and
  `check-suite-inventory.py` for both suites: all pass.
- The two inherited gate failures were reproduced on a `git archive` of base
  8bb344e32, independently of the record above: `check-vulture-baseline.py`
  exits 1 on both (1430 findings at base, 1429 here — the branch removes one;
  `quality/vulture-baseline.json` has no diff), and `check-ac-state.py
  --run-tests --ratchet` exits 1 on both with the identical design_coverage
  33.0281 below the 33.9095 floor, while this head's per-change acceptance
  mandate (22 criteria, 0 unproven) and chain mandate pass.
- Transport census re-derived at this head: the only production outbound
  transports are httpx through `maistro.http` and the five guarded Playwright
  entry points; no `aiohttp`/`urllib.request`/`requests`/raw outbound socket
  exists outside `security/ssrf.py`'s resolver and config parsing.

No code change was needed in this phase; the prior findings (unguarded
`hill-climb-ui.sh` contexts, its Hyperlight dispatch, and the SECURITY.md
enumeration gap) were already fixed on this branch and are pinned by
`test_hyperlight_hill_climb_guards_each_sync_browser_context`.
