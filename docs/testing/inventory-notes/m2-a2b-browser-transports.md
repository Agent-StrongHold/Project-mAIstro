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

Repair-phase re-verification record (L155, head 57b9d4a4c, 2026-09-23)
----------------------------------------------------------------------

The previous verifier pass was mechanically rejected only because its own
inventory commit changed the worktree mid-run ("verification worktree
changed; evidence rejected"). This pass re-executed the battery at the
stable head 57b9d4a4c and confirmed the two inherited gate failures
against the base tree directly, not from the earlier record:

- `uv run pytest packages/maistro-core/tests/tools/browser -q` → 131
  passed, 0 skipped; `test_playwright_transport.py` re-run verbosely → all
  4 real-Chromium proofs PASSED, including
  `test_real_chromium_rechecks_a_redirect_before_the_private_connection`.
- `uv run pytest packages/hive-conductor/backend/tests/test_browser_network_policy.py
  packages/hive-conductor/backend/tests/test_engine_service.py -q` → 38 passed.
- `uv run pytest packages/maistro-core/tests/security -q` → 1255 passed,
  1 failed (`test_log_redaction.py::test_install_is_idempotent`); that
  failure reproduces identically in a detached base-8bb344e3 worktree
  running its own `--locked --all-extras` env, and the base→head diff
  touches no redaction file — pre-existing, unrelated to egress.
- Gates: `ruff check .`, `ruff format --check .`,
  `check-suite-inventory.py` (both suites), `check_direct_effects.py`,
  `check-security-inventory.py` (63 paths / 23 rows),
  `check-model-egress.py` (23 direct callers, no expansion) — all pass.
- `check-vulture-baseline.py` rc=1 re-derived as inherited: head scan
  finds 1429 findings vs 1430 in a fresh base-8bb344e3 scan (the single
  delta is this branch's removal of `run_hill_climb.py::COMPONENT_PATH`),
  and `quality/vulture-baseline.json` is byte-identical base→head.
- `check-ac-state.py` floor gap re-derived as inherited: a measurement
  run (`--run-tests --out`, no `--ratchet`) at detached base-8bb344e3
  reports design_coverage 33.0281% over 155 decisions — the per-decision
  dict is byte-equal to head's committed `quality/ac-state.json`. The
  branch moves coverage by exactly 0.0000; the 33.9095 floor undercut is
  develop-base debt. (Operator note: `--compact` is a short-circuit that
  only compacts note ledgers and measures nothing — it rewrites
  `quality/ac-state-notes/` as a side effect. The ledger churn it caused
  here was restored byte-for-byte from HEAD before committing; use plain
  `--run-tests --out <path>` for measurement.)
- Transport census re-swept: production Playwright entry points are
  exactly `tools/browser/client.py`, `ui_auto_climb.py`, `widgets.py`,
  `run_hill_climb.py`, `hill-climb-ui.sh`; `browser_use` only in
  `tools/browser/`; no closure reference (`fixes/closes/resolves #N`) in
  any of the 19 branch commit messages.

Repair-writer re-derivation at the stable head e2811241e (L155, 2026-09-24)
---------------------------------------------------------------------------

The previous repair run died on a provider context overflow before touching
the tree, so this round re-executed every inherited claim from scratch at
head e2811241e. Nothing above was trusted without re-measurement:

- Test batteries: `uv sync --locked --all-extras` (installs the `browser`
  extra, playwright 1.63.0), then `pytest packages/maistro-core/tests/tools/browser`
  → 131 passed, and `test_playwright_transport.py` → all 4 real-Chromium
  proofs pass (the earlier "4 skipped" state is the missing-extra
  environment, not a skip on this tree). `pytest
  packages/hive-conductor/backend/tests/test_browser_network_policy.py
  packages/hive-conductor/backend/tests/test_engine_service.py` → 38
  passed. `pytest packages/maistro-core/tests/security` → 1255 passed,
  1 failed (`test_log_redaction.py::test_install_is_idempotent`); that
  failure reproduces identically in the detached base-8bb344e3 worktree
  (`/home/dev/Git/worktrees/base-8bb344e3-verify`) and the base→head diff
  touches no redaction file — pre-existing, unrelated to egress.
- `check-vulture-baseline.py` rc=1 re-derived as inherited with a
  scan-level identity diff, not just ledger equality: fresh vulture scans
  of the base tree (1430 findings) and head tree (1429) classified under
  the shared ledger rules give, per rule, identical deltas vs the ledger
  for every rule (e.g. fastapi-route-handler 205 new / 10 stale at BOTH
  base and head), with exactly one base-only identity —
  `run_hill_climb.py::COMPONENT_PATH`, fixed by this branch — and zero
  head-only identities. The ledger is byte-identical across base,
  origin/develop (1dea30dfe) and head, so the merge base fails the gate
  the same way; and since `quality/ratchet-authorizations.json` carries no
  vulture grants, even a candidate `--update` cannot clear the
  unauthorized-vs-trusted path. Not repairable inside this lane; the
  branch is strictly debt-neutral-to-better.
- `check-ac-state.py --run-tests --ratchet --mandate 3e9f7525…` rc=1
  re-derived as inherited and the earlier 31.769% reading corrected: with
  the full extras environment a fresh head measurement (`--run-tests --out`)
  reports design_coverage **33.0281% over 155 decisions**, per-decision
  dict byte-equal to the committed `quality/ac-state.json` AND to a fresh
  base-8bb344e3 measurement run the same way. The branch moves design
  coverage by exactly 0.0000; the 33.9095 floor is already undercut at the
  merge base. The acceptance mandate itself passes at head: "every
  criterion this change declares is proven" (22 added/newly-claimed since
  the mandate base, 0 unproven-undeclared); the ratchet's single FAIL line
  is the floor undercut. The 31.769% in the prior verifier artifact was an
  environment artifact of measuring without the browser extra.
- Gates re-run green at head: `ruff check .`, `ruff format --check .`,
  `check-security-inventory.py` (63 paths / 23 rows),
  `check-model-egress.py` and `check_direct_effects.py` (50 direct
  callers, all dispositioned), `check-suite-inventory.py` (13 suites).
- Acceptance mapping re-verified in the tests themselves: explicit browse
  (`test_client.py::test_browse_runs_on_a_guarded_session_too`,
  `test_browse_denies_a_redirect_hop_into_a_private_target`),
  search/model-directed navigation
  (`test_search_web_attaches_the_guard_before_the_agent_sees_the_context`,
  `test_search_web_denies_a_destination_the_model_invented`,
  `test_browser_session_creating_its_own_context_is_governed`),
  redirect-to-private (`test_net_guard.py::test_a_redirect_hop_from_public_to_private_is_denied_at_that_hop`,
  real-Chromium
  `test_real_chromium_rechecks_a_redirect_before_the_private_connection`),
  scoped internal allowances
  (`test_a_configured_origin_is_allowed_and_the_allowance_stays_scoped`,
  `test_host_configured_browser_origins_are_reachable_and_scoped`).
  Reaching a private target from a permitted public start through browser
  navigation is refused at the hop that matters, at the actual Playwright
  route boundary — no fake HTTP wrapper involved.

## L155 independent verifier pass at a2b9880ff (2026-09-24)

Verify-phase pass at the lane head `a2b9880ff` (merge of develop
`1dea30dfe` into auto-155; the repair work at `e2811241e`/`b937c2be0` is an
ancestor and survived the merge — none of the guarded call sites regressed).

Re-executed at this head, with `uv sync --all-extras` (the pyproject-
documented install for the browser extra; the verify driver's plain
`uv sync` had removed playwright):

- Core browser battery `pytest packages/maistro-core/tests/tools/browser/`:
  **127 passed, 4 skipped → re-run with playwright installed: the 4
  real-Chromium transport proofs pass** (redirect-to-private denied before
  the private server receives anything, allowed redirect followed inside
  the guard, model-directed loopback refused pre-connect, exact-origin
  scoping). Conductor battery `test_browser_network_policy.py +
  test_engine_service.py`: **38 passed**, including the source assertions
  that keep `hill-climb-ui.sh` on `guarded_context`/`sync_client`.
- Security battery `tests/security/`: **1261 passed, 1 failed** —
  `test_log_redaction.py::test_install_is_idempotent`. Reproduced
  identically at base `1dea30dfe` in a detached worktree; the base→head
  diff touches no redaction file. Pre-existing environment drift, not a
  branch regression.
- Inherited-gate re-derivation at this head: `check-vulture-baseline.py`
  rc=1, but the 116 files carrying "NEW identity" findings have an **empty
  intersection** with the branch's 19 changed files, and head scans 1429
  findings vs base 1430 (one fixed, none added). `check-ac-state.py`
  rc=1 is only the design-coverage floor: the 33.9095 floor is a note
  banked at `93401f348` (`chatgpt-issue-729-...`, `measured_with_tests`);
  the fresh head measurement is **33.0281% over 155 decisions, byte-equal
  to the committed per-decision dict**, the branch moves coverage by
  exactly 0.0000 and touches no ac-state note, and the change's own
  acceptance mandate passes (22 criteria, 0 unproven). Both failures are
  present at the merge base and out of this branch's scope to bank.
- Gates green at head: `ruff check .`, canonical mypy (713 files, 0
  issues), `check-security-inventory.py` (63 paths / 23 rows),
  `check_direct_effects.py` (50 sites, all dispositioned),
  `check-suite-inventory.py` (13 suites).
- Transport census re-done at the merge head: every Playwright entry point
  (BrowserClient, `ui_auto_climb.screenshot`, `widgets.capture_screenshot`,
  `run_hill_climb.py` ×2, `hill-climb-ui.sh` ×2) attaches a guard before
  the first page; `design_render`'s Playwright renderer still refuses
  (unimplemented); no aiohttp/urllib/raw-socket outbound transports exist
  in production code. PR body and branch commits carry no closure keyword
  ("Refs #155" only).

## L155 repair-writer re-derivation at the stable head b8ecf38a8 (2026-09-24)

Repair round against the develop base `60862b6c5eb1` (note: the ratchet
scripts resolve their *trusted* ledger base to `1dea30dfe30c`, an ancestor of
that develop base, via event metadata). The prior finding set named the
`hill-climb-ui.sh` browser transport, its Hyperlight dispatch, the SECURITY.md
enumeration, and the two inherited gate failures. Nothing was carried forward;
every claim below was executed at this head:

- Findings 1–3 (unguarded `hill-climb-ui.sh` contexts, `ui_climb_vm.py`
  reachability, SECURITY.md omission) do **not** reproduce at this head: the
  fix landed on this branch in `5b3cac761` ("govern hyperlight hill-climb
  browser transport"), an ancestor of the prior verify head `a2b9880ff` —
  the finding text quotes the pre-fix line numbers. Re-proofs executed:
  `test_hyperlight_hill_climb_guards_each_sync_browser_context` pins the
  script source (`configure_outbound_policy(BASE, URL)`, `sync_client` for
  scoring, `service_workers="block"`, `SyncBrowserNetworkGuard...attach` on
  both context creations, no unguarded `browser.new_page(`); the embedded
  heredoc Python compiles after shell-variable substitution; the four other
  Playwright entry points (`tools/browser/client.py`, `ui_auto_climb.py`,
  `widgets.py`, `run_hill_climb.py`) each attach the guard before the first
  page. SECURITY.md rows 167–168 name all five transports, including
  "`hill-climb-ui.sh`, the script the Hyperlight UI-climb workload
  dispatches", and keep the honest `partial`/separate-Chromium wording.
- Batteries re-run at this head: core browser `pytest
  packages/maistro-core/tests/tools/browser/ -q` → **131 passed, 0 skipped**
  (playwright present), including all four real-Chromium transport proofs by
  name (`test_real_chromium_rechecks_a_redirect_before_the_private_connection`:
  the private server receives zero requests). Conductor
  `test_browser_network_policy.py` + `test_engine_service.py` → **38
  passed**. Ordinary-HTTP seam `test_outbound_policy.py` + `test_transport.py`
  + `test_ssrf.py` → **173 passed**.
- Gates green at head: `ruff check .`, `ruff format --check .`,
  `check-security-inventory.py` (63 paths / 23 rows),
  `check-suite-inventory.py` for both suites, `check_direct_effects.py`
  (50 sites, all dispositioned), `check-model-egress.py` (23 direct callers,
  no expansion).
- Finding 4 (`check-vulture-baseline.py` rc=1) re-derived as **inherited**, at
  scan level: a detached base-`60862b6c` worktree scanned with the same
  interpreter and classified under the base's own (byte-identical) ledger
  yields the identical rule-level drift (core-public-api-surface −544,
  pytest-discovered-test-surface +448, fastapi-route-handler +206/−10, …);
  the base run itself bails early on its self-resolution guard before delta
  checking, which is why prior base logs look clean. Head scans 1429 findings
  vs base 1432; the ledger `quality/vulture-baseline.json` is byte-identical
  across base, `1dea30dfe` and head; no branch-changed file appears in the
  drift. Clearing it needs a reviewed ledger grant — out of scope for an
  ordinary repair.
- Finding 5 (`check-ac-state.py --run-tests --ratchet` rc=1) re-derived as
  **inherited**: the same command at the detached base worktree with
  `RATCHET_BASE_REV=1dea30dfe…` (matching the head run's trusted base)
  reports the identical `design coverage: 33.0281% over 155 taken decisions
  (93 at zero)` and fails against the same 33.9095 floor with the identical
  message. The branch moves design coverage by exactly 0.0000; the
  per-change mandate at head stays green (22 criteria claimed, 0 unproven).
  Banking the fall would be a ledger edit — out of scope for an ordinary
  repair.
- No code change was needed in this round; the only edit is this record.

Independent verification record (L155, head f19ead10a, 2026-09-24)
------------------------------------------------------------------

Re-derived at the post-merge head `f19ead10a` (merge of develop `60862b6c5`
into the repair head `50ecb72e`). Every claim below was executed at this head,
not carried forward from the b8ecf38a8 record:

- Driver checks re-run locally: `ruff check .` + `ruff format --check .`
  clean; core browser suite 127 passed; conductor `test_browser_network_policy`
  + `test_engine_service` 38 passed; both `check-suite-inventory.py` runs ok.
- The develop merge removed `playwright` from the dev lock (the driver's
  `uv sync --locked` uninstalls it), so the four integration proofs in
  `test_playwright_transport.py` skip in the locked venv. They were re-run for
  real at this head after a venv-only `uv pip install playwright==1.63.0`
  (the version the sync removed; no tracked file changed): **131 passed,
  0 skipped**, including all four real-Chromium proofs —
  `test_real_chromium_rechecks_a_redirect_before_the_private_connection`
  asserts the private server received **zero requests** after a public 302
  into it, i.e. the redirect-to-private criterion is proven at the actual
  Chromium route boundary, not through a fake wrapper.
- Gates green at this head: `check_direct_effects.py` (50 sites, all
  dispositioned), `check-security-inventory.py` (63 paths / 23 rows),
  `check-model-egress.py` (23 direct callers, no expansion). SECURITY.md
  rows 167–168 still enumerate all five Playwright transports (client.py,
  ui_auto_climb.py, widgets.py, run_hill_climb.py, hill-climb-ui.sh) with the
  honest `partial`/separate-Chromium wording; the embedded hill-climb-ui.sh
  heredoc Python still compiles after shell-variable substitution.
- `check-vulture-baseline.py` rc=1 re-confirmed **inherited**: a detached
  base-`60862b6c5` worktree, scanned with the same interpreter and
  `RATCHET_BASE_REV=1dea30dfe`, reproduces the identical rule-level drift
  (same NEW identities in `hive-conductor/dags/__init__.py:48` and
  `dags/author_selector.py:204`, same pruned `maistro_bootstrap/session.py`
  identity). The branch changes none of the drift files and leaves
  `quality/vulture-baseline.json` byte-identical. Clearing it needs a
  reviewed ledger grant — out of lane scope.
- `check-ac-state.py --run-tests --ratchet` rc=1 re-confirmed **inherited**:
  the same command at the detached base worktree reports the identical
  `design coverage: 33.0281% over 155 taken decisions` failing the same
  33.9095 floor; the branch moves coverage by exactly 0.0000 and the
  per-change mandate at head is green (22 criteria claimed, 0 unproven).
- One extra inherited red found and dispositioned this round:
  `packages/maistro-core/tests/security/test_log_redaction.py::
  test_install_is_idempotent` fails inside the full security-suite run
  (1261 passed / 1 failed) and fails identically at the detached base
  worktree with the same interpreter; the branch touches none of
  `log_redaction.py` / `redact.py` / that test file.
- No premature closure keywords: PR 1451 body says "Refs #155" only; no
  branch commit message contains a `Fixes/Closes/Resolves #N` trailer (the
  `dc3df6b63` subject uses "close" as a verb, which auto-closes nothing).
