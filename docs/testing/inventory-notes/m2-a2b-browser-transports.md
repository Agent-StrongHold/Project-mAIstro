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

## L155 repair-round writer re-derivation at af89fb2a9 (2026-09-23)

Fresh execution at the lane head
`af89fb2a91d1c0f2c428daa66d8dc971741a1634` (develop base
`8bb344e32b8693574fc0be7a93f86d941616b62c`), independent of the two verifier
passes above:

- `ruff check .` and `ruff format --check .` → both rc=0 (2528 files).
- Browser seam: `uv run pytest packages/maistro-core/tests/tools/browser -q`
  → **131 passed**, including all four real-Chromium transport proofs
  (`test_real_chromium_rechecks_a_redirect_before_the_private_connection`,
  `..._follows_an_allowed_redirect_inside_the_guard`,
  `..._denies_model_directed_loopback_before_connect`,
  `..._can_read_only_the_configured_origin` — the guard is exercised at the
  actual Playwright route boundary with a real Chromium, not a mock).
- Conductor: `test_browser_network_policy.py` + `test_engine_service.py` →
  **38 passed**. Ordinary-HTTP seam: `test_outbound_policy.py` +
  `test_transport.py` + `test_ssrf.py` → **173 passed**.
- Gates: `check-security-inventory.py`, `check-model-egress.py`,
  `check_direct_effects.py`, and `check-suite-inventory.py` for both suites →
  all rc=0.
- Inherited non-green, re-reproduced with exact evidence:
  `check-vulture-baseline.py` rc=1 at head **and** at a fresh
  `git archive` of the base; the base→head drift diff is exactly the one
  *fixed* identity (`run_hill_climb.py::COMPONENT_PATH`, 1430 → 1429
  findings) plus the header lines naming the revisions — zero new debt, no
  branch file in the drift.
- **New this round — ac-state base measurement executed**, not just claimed:
  a detached base worktree at `8bb344e3` measured with the script's own
  method (`AC_STATE_BASE_MEASUREMENT=1 uv run --project <base> --locked
  --all-extras python scripts/check-ac-state.py --run-tests`) reports
  `design_coverage: 33.0281%` over 155 taken decisions — byte-equal to the
  head measurement (33.0281%). The branch moves design coverage by exactly
  0.0000; the recorded floor (33.9095, folded from 72 notes "at 8bb344e3")
  is not reproducible on the base revision itself in this environment, so the
  floor undercut is inherited repository/environment state, not a regression
  of this branch. The per-change mandate at head stays green (22 criteria
  claimed, 0 unproven) and the chain mandate reports zero absent links.
  Banking the fall would be a ledger edit, which is out of scope for an
  ordinary repair PR.
- Transport census re-swept at this head: still exactly five production
  Playwright entry points, each guard-attaching (sync or async) before its
  first page; the only three non-core `httpx.Client`/`AsyncClient`
  constructions (`maistro-bootstrap` model_selector, `maistro-design`
  open_design, `maistro-evolve` openai_compatible) predate the branch
  (untouched by base→head diff; last governed by merged #1308) and are
  outside the maistro-core seam census SECURITY.md's recomputed claim covers.

## L155 independent verifier pass at b77dabbfe (2026-09-23)

Fresh execution at the lane head
`b77dabbfef0b3e637edd960db7c387821b14791a` (develop base
`8bb344e32b8693574fc0be7a93f86d941616b62c`); nothing carried forward from the
rounds above:

- Browser seam: `uv sync --locked --extra dev --extra browser`, then
  `uv run pytest packages/maistro-core/tests/tools/browser/ -q` →
  **131 passed, 0 skipped**, including all four real-Chromium transport
  proofs verified individually by name (redirect-to-private denied before
  the private server receives a request; allowed in-guard redirect chain;
  model-directed loopback denied pre-connect; only-the-configured-origin
  readable). Conductor `test_browser_network_policy.py` +
  `test_engine_service.py` → **38 passed**. Ordinary-HTTP seam
  `test_outbound_policy.py` + `test_transport.py` + `test_ssrf.py` →
  **173 passed**.
- Gates: `ruff check .` and `ruff format --check .` clean;
  `check-security-inventory.py` rc=0 (63 paths resolve, 23 rows match);
  `check-model-egress.py` rc=0; `check_direct_effects.py` rc=0 (50 sites,
  every site dispositioned).
- Inherited non-green, re-reproduced with my own base worktree
  (`git worktree add --detach /tmp/maistro-base-8bb344 8bb344e3`), not a
  carried claim: `check-vulture-baseline.py` rc=1 at head (1429 findings)
  and at base (1430 findings); the ledger `quality/vulture-baseline.json`
  has no base→head diff, no branch-changed file appears in the head drift
  output, and the single-identity delta is the branch's *fix*
  (`run_hill_climb.py::COMPONENT_PATH` no longer exists at head).
  `check-ac-state.py --run-tests --ratchet --mandate 3e9f7525…` rc=1 at
  head (design_coverage 33.0281 < 33.9095 floor); a measurement-only run at
  the base worktree (`--run-tests --out`, no `--ratchet`, rc=0) reports
  **33.0281% over 155 taken decisions (93 at zero)** and the base/head state
  JSONs are byte-equal across every counter — the branch moves design
  coverage by exactly 0.0000, so the floor undercut is develop-base debt.
  Per-change mandate at head: 22 criteria claimed, 0 unproven; chain
  mandate: zero absent links.
- Pre-existing environment-dependent failure re-confirmed on both heads:
  `test_log_redaction.py::test_install_is_idempotent` fails identically at
  base and at this head (unrelated to egress).
- Transport census re-swept at this head: exactly five production Playwright
  entry points (`tools/browser/client.py`, `ui_auto_climb.py`,
  `widgets.py`, `run_hill_climb.py`, `hill-climb-ui.sh`), each guard-attaching
  before its first page; `browser_use` imported only by
  `tools/browser/client.py`; no `aiohttp`/`urllib.request`/`requests` import
  in production code; `maistro-core` constructs raw httpx clients only
  inside `maistro/http.py` itself. The three non-core raw httpx clients
  (`maistro-bootstrap` model_selector, `maistro-design` open_design,
  `maistro-evolve` openai_compatible) and the UDS-only Docker client
  (`containers.py`, no IP destination) are untouched by the base→head diff.
- Closure keywords: none in the PR #1451 body ("Refs #155" only, draft) nor
  in any of the 19 branch commit messages.
