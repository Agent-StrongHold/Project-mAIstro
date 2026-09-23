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

Post-repair verifier re-execution (L155, head 6aa0360c1, 2026-09-23)
--------------------------------------------------------------------

Independent re-run at this exact head; nothing carried forward:

- `uv run pytest packages/maistro-core/tests/tools/browser/ -q` → 127 passed
  (4 real-Chromium tests skip until playwright is present).
- playwright 1.63.0 installed into the (gitignored) venv; `.venv/bin/python
  -m pytest .../test_playwright_transport.py -q` → 4 passed with the cached
  real Chromium, including
  `test_real_chromium_rechecks_a_redirect_before_the_private_connection` and
  `test_real_chromium_denies_model_directed_loopback_before_connect`.
- `test_ssrf.py` + `test_outbound_policy.py` + `test_transport.py` → 173
  passed. Conductor `test_browser_network_policy.py` +
  `test_engine_service.py` → 38 passed.
- `ruff check .` and `ruff format --check .` clean;
  `check-security-inventory.py`, `check-model-egress.py` (with the
  direct-effects census), `verify-monorepo-layout.sh`,
  `check-suite-inventory.py` (both suites, driver logs): pass.
- Mandate: `check-ac-state.py --run-tests --mandate 3e9f7525…` → 22 criteria
  claimed, 0 unproven, chain mandate OK, rc=0.
- Transport census re-derived: still exactly five production Playwright entry
  points, all guard-attaching; `browser_use` imported only by
  `tools/browser/client.py`; no aiohttp/urllib.request/requests/raw outbound
  socket; `tool_executor.py` reaches Chromium only via the guarded
  `BrowserClient`. No closure keyword in any commit message or the PR body.
- The three known non-green items reproduce identically on a `git archive` of
  base 8bb344e32: `check-vulture-baseline.py` rc=1 (same categories, no
  branch file in the output, ledger diff empty), `check-ac-state.py
  --run-tests --ratchet` rc=1 (design_coverage 33.0281 < 33.9095 on both),
  and `test_log_redaction.py::test_install_is_idempotent` (fails on both
  heads). All inherited, none introduced by this branch.

Repair-phase re-verification (L155, head 8b1c705b2, 2026-09-23)
---------------------------------------------------------------

Re-executed at the final head after the inventory-only commit; code is
identical to 6aa0360c1 and every claim above was re-derived, not carried:

- `uv run pytest packages/maistro-core/tests/tools/browser/ -q` → **131
  passed** with playwright installed in the venv: the 127 transport-level
  tests plus all 4 real-Chromium tests in one run, including the
  redirect-to-private and model-directed-loopback proofs (real HTTP servers,
  private server asserted to receive zero requests).
- Security seam: `test_outbound_policy.py` + `test_transport.py` +
  `test_ssrf.py` → 181 passed; `test_log_redaction.py::
  test_install_is_idempotent` fails here and on the base archive alike
  (environment-dependent, pre-existing, unrelated to egress).
- Conductor: targeted `test_browser_network_policy.py` +
  `test_engine_service.py` → 38 passed; **full backend suite**
  `uv run pytest packages/hive-conductor/backend/tests -q` → 2654 passed,
  1 skipped.
- Gates: `ruff check .`, `ruff format --check .`,
  `check-direct-effects`/census, `check-model-egress.py`,
  `check-security-inventory.py`, `check-suite-inventory.py` (both suites) →
  all rc=0.
- Inherited non-green reproduced fresh on this head and on the base archive:
  `check-vulture-baseline.py` rc=1 with a byte-identical drift diff (no
  branch file involved; ledger edits are out of scope for an ordinary
  repair), and `check-ac-state.py --run-tests --ratchet` rc=1 with the same
  design_coverage 33.0281 < 33.9095 floor on both heads — while the
  per-change mandate passes (22 criteria claimed, 0 unproven). Both are
  develop-base debt, not this branch's regression.
- Transport census re-swept: still exactly five production Playwright entry
  points (`tools/browser/client.py`, `ui_auto_climb.py`, `widgets.py`,
  `run_hill_climb.py`, `hill-climb-ui.sh`), each attaching the sync or async
  guard before its first page; `browser_use` imported only by
  `tools/browser/{client,guard}.py`; no aiohttp/urllib.request/requests/raw
  outbound socket in production paths; `tool_executor.py` reaches Chromium
  only via the guarded `BrowserClient`; `task_backend.py` uses the guarded
  `sync_client` seam with its base origin allowlisted.

## L155 independent verifier pass at 080b4e0e5 (2026-09-23)

Re-derived acceptance at the lane head `080b4e0e5f5b542bcac52c15fd4fb7a3ae836bb2`
(develop base `8bb344e32b8693574fc0be7a93f86d941616b62c`), executing every check
fresh rather than trusting the repair-phase record:

- Browser seam: full `packages/maistro-core/tests/tools/browser/` →
  **131 passed** with the `browser` extra installed (`uv sync --locked --extra
  dev --extra browser`), including all 4 `test_playwright_transport.py`
  real-Chromium proofs — notably
  `test_real_chromium_rechecks_a_redirect_before_the_private_connection`
  (public→private redirect; the private server received zero requests).
  Conductor `test_browser_network_policy.py` + `test_engine_service.py` →
  **38 passed**. Ordinary-HTTP seam `test_outbound_policy.py` +
  `test_transport.py` + `test_ssrf.py` +
  `test_outbound_gateway_policy.py` → **183 passed**.
- Gates re-run at this head: `ruff check .` rc=0;
  `check-security-inventory.py` rc=0; `check-model-egress.py` rc=0;
  `check_direct_effects.py` rc=0.
- Inherited non-green re-reproduced: `check-vulture-baseline.py` rc=1 at this
  head and at a fresh `git archive` of the develop base. **Correction to the
  repair-phase note:** the two drift logs are *not* byte-identical — the diff
  is exactly one finding, `run_hill_climb.py::COMPONENT_PATH` (1430 findings at
  base → 1429 at head): this branch *fixed* that identity and added no new
  debt; no branch file appears anywhere in the drift. The floor failure in
  `check-ac-state.py --run-tests --ratchet` reproduces identically on both
  heads (design_coverage 33.0281 < 33.9095) with the per-change mandate green
  (22 criteria claimed, 0 unproven) — develop-base debt either way.
- Acceptance sweep re-executed: five production Playwright entry points, each
  guard-attaching before its first page; `browser_use` reachable only via the
  guarded `BrowserClient`; `tool_executor.py` Chromium fallback goes through
  `BrowserClient`; no aiohttp/urllib.request/requests/raw outbound sockets in
  production code; `task_backend.py` raw `httpx.Client` replaced by the
  guarded `sync_client` (test-enforced). SECURITY.md rows 167–168 separate the
  HTTP and Chromium transports without implying shared-client coverage reaches
  Chromium.
- PR #1451 body and branch commit messages checked for closure keywords: none
  ("Refs #155" only; PR is a draft).
