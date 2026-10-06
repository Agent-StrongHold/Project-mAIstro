---
inventory-delta:
  packages/maistro-core/tests: +30
---
# auto-950 — M9-A2 canonical extension context and lifecycle (#950)

Adds the `packages/maistro-core/tests/extensions/` suite pinning the new
public extension contract (`maistro.extensions`, ADR-104, issue #950). The
30 tests split across two files by what they pin:

- `test_extension_contract_conformance.py` (24) — the interface contracts
  themselves, independent of any one extension implementation: the closed
  public context surface (no store/container/db handles, `__slots__`-pinned,
  and the host-side config/service mappings filtered against the descriptor
  before they reach context storage), declared-only configuration access,
  service grants requiring declaration AND host grant, effect dispatch
  requiring declaration AND route plus a cancellation pre-check, governed
  routes refusing cross-workspace dispatch, lifecycle drivers refusing
  hook/context scope mismatches before any hook code runs, the cancellation
  view's read-only semantics over the canonical task fence (including never
  swallowing `CancelledError`), progress-hook validation, structural
  lifecycle protocol conformance, extension-attributed lifecycle error
  wrapping, and the suite's own SDK-only import closure (ADR-104 AC-5).

- `test_extension_reference_execution.py` (6) — a reference extension
  executing through the canonical `Graph → Run → NodeRun → Attempt` path
  (`AttemptExecutionService` over `PythonExecutionRuntime`): its governed
  effect produces a real canonical `Invocation` row with full correlation,
  provenance and progress land on the canonical event stream with the
  extension identity in the envelope `provenance` field, undeclared effects
  and activation-scope dispatch are refused, a route resolved for one
  workspace refuses a scope carrying another's workspace id, and
  `service.cancel(attempt_id)` reaches the extension's cancellation view
  while the Attempt settles CANCELLED with NodeRun/Run terminal.

Delta history within this lane: +26 at `f348fa3e0bfb`; +1
(`test_governed_route_refuses_cross_workspace_dispatch`, commit `002113aa8`);
+1 (`test_host_drops_undeclared_config_and_service_grants`, commit
`6183194cd`); +1 (`test_lifecycle_drivers_enforce_hook_scope_pairing`); +1
(`test_conformance_suite_binds_no_concrete_extension`, pins ADR-104 AC-5) =
+30. No existing tests were removed or renamed; the delta is purely additive.

## Validation battery (executed at head `f348fa3e0bfb…`, branch `auto-950`)

Re-executed after the CI-repair round on top of `869f936f525e` — the repair
(`CORE_PUBLIC_SURFACE` enumeration, ADR-104 `related` reclassification,
`EventStoreProgressSink` M1 projection marker) changed no test, so the counts
below are unchanged; the newly executed provenance gates are appended.

- `uv run ruff check .` → All checks passed (exit 0); `ruff format --check .`
  → 2926 files already formatted.
- `uv run mypy --strict packages/maistro-core/src/maistro/extensions
  packages/maistro-core/src/maistro/runtime/__init__.py` → Success, no issues.
- `uv run pytest packages/maistro-core/tests -q` (minus `tests/integration`,
  the known services-down set) → **12422 passed, 888 skipped, 1 xfailed**.
- `uv run pytest packages/maistro-server/tests packages/maistro-design/tests
  packages/maistro-registry/tests -q` → **1039 passed, 9 skipped** (the root
  package's import graph changed in this lane, so sibling importers were run).
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0; 1338 reviewed
  identities → 1338 findings; `unclassified: 0`. The SDK's external-only
  methods are referenced in `packages/maistro-core/src/_vulture_whitelist.py`
  (public-surface mechanism; no `quality/*.json` rows added).
- `uv run python scripts/check-reachability.py` → exit 0; the six new modules
  are wired through the documented `maistro.runtime` anchor.
- `uv run python scripts/check-promotion-surface.py` → exit 0 (an earlier
  draft anchored the SDK in the package root, which dragged the
  capabilities/events/policy/credentials subgraph onto the promotion path;
  that anchoring was replaced — see ADR-104 §7).
- `scripts/check-radon-baseline.py` (143=143), `check-suite-inventory.py`
  (14 suites ok), `check-contract-markers.py` (ADR-104 evidenced by the
  `contract: behavioral` markers on both new test files), `check-adr-index.py`,
  `check-ac-state.py`, `check-doc-links.py` → all exit 0.
- A ledger `--update` run against `quality/contract-markers-baseline.json`
  was reverted unused; the ADR-104 claim is evidenced by markers instead.
- `RATCHET_BASE_REV=origin/develop uv run python
  scripts/check-ratchet-provenance.py` (the `exact-debt-ledger` portfolio,
  CI's exact step) → exit 0 after the repair: citation-status 0 exceptions,
  enumerations 1 tolerated gap, adr-status-language / promotion-surface /
  reachability / reachability-dispositions / shell-execution /
  contract-markers / lifecycle all flat vs the trusted base.
- `uv run python scripts/check_enumerations.py` → exit 0, no new gaps
  (`maistro.extensions` is enumerated in `CORE_PUBLIC_SURFACE`,
  `scripts/verify-wheel-imports.py`).
- `uv run python scripts/check-citation-status.py` → exit 0 (SPEC-177 cited
  as `related`, not governing `substrate`, in ADR-104).
- `python scripts/check-m1-convergence-freeze.py --base 94781cf6` → exit 0
  (`EventStoreProgressSink` docstring carries the policy's own
  `M1 product-local projection: Event` classification).
- `tests/test_check_citation_status.py` root self-checks (the ones CI's
  `test` job and the coverage combine step run) → pass; plus
  `tests/test_verify_wheel_imports.py`, `tests/test_check_enumerations.py`,
  `packages/maistro-core/tests/extensions`, `packages/maistro-registry/tests`
  → 313 passed total across the repair battery.
- `scripts/check-diff-coverage.py` (branch coverage over the changed
  measured files) → ok at 90% lines / 80% branch floors.
- `scripts/check-adr-index.py`, `maistro_registry.cli lint . --strict`,
  `scripts/check-doc-links.py`, `scripts/check-ac-state.py`,
  `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` (1338=1338, `unclassified: 0`) → all exit 0;
  `quality/` is byte-identical to the base (no ledger rows added).

## Validation battery (re-executed at head `6183194cdc30` + the scope-pairing
## salvage round, branch `auto-950`)

Re-executed after the two follow-up fixes (`002113aa8` cross-workspace
refusal, `6183194cd` undeclared-grant filtering at host composition) and the
uncommitted scope-pairing enforcement in the lifecycle drivers, plus the
ADR-104 acceptance-criteria retrofit (AC-1..AC-5 with `@pytest.mark.ac`
markers, module-identity anchors, and the earned design-coverage bank). With
a live migrated pgvector/pg18 (`docker run pgvector/pgvector:pg18`, alembic
head):

Executed this round (all exit 0 unless stated):

- `uv run ruff check .` and `uv run ruff format --check .` (2931 files).
- `uv run mypy --strict packages/maistro-core/src` → 712 files clean (after
  `uv sync --locked --all-extras`; with `--extra dev` only, the bootstrap
  import-not-found errors are environmental, not findings).
- `uv run pytest packages/maistro-core/tests -q` minus `tests/integration`,
  with `MAISTRO_TEST_PG_DSN` against the live migrated pg18 → **13133
  passed, 198 skipped, 1 xfailed** (the earlier "12422 passed / 888 skipped"
  figure ran without PG; the two `test_schedule_winner_crash.py` pg cases are
  latency-sensitive and failed 3/3 in one isolated re-run, then passed in
  the full-suite runs — their subsystem is byte-identical from this branch's
  fork point through current develop, so the flake is not this lane's).
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` → 1338=1338, exit 0; xenon 143 blocks ≤ 145,
  0 module/average violations; pyright 21 = baseline 21; radon ratchet ok.
- `RATCHET_BASE_REV=origin/develop uv run python
  scripts/check-ratchet-provenance.py` → exit 0; all ten ratchets flat vs
  the trusted base (merge-base 1885c8eda); `check-shipped-surface-truth.py`,
  `check_enumerations.py`, `check-reachability.py`,
  `check-reachability-dispositions.py`, `check-convergence-matrix.py`,
  `check-contract-markers.py`, `check-execution-lifecycles.py`,
  `check-doc-links.py`, `check-adr-index.py`, `check-workspace-retirement.py`,
  `check-route-permissions.py`, `check-principal-identity.py`,
  `check-frontend-typed-client.py`, `check-model-egress.py`,
  `check-foreign-harness-egress.py`, `check-security-inventory.py`,
  `check-agent-store-writes.py`, `check-wiring-reads.py`,
  `check-backlog-consistency.py`, `bump_version.py --check`,
  `check-release-consistency.py`, `check-m1-convergence-freeze.py --base
  1885c8eda` → all exit 0.
- `scripts/check-diff-coverage.py` (coverage over the extensions suite plus
  `tests/test_verify_wheel_imports.py` under `--source=scripts`, base
  1885c8eda) → ok at 90% lines / 80% branch floors.
- `tests/test_verify_wheel_imports.py tests/test_check_enumerations.py
  tests/test_check_citation_status.py` → 282 passed;
  `maistro_registry.cli lint . --strict` → 431 files clean.
- `scripts/check-suite-inventory.py` → 14 suites match (this note carries the
  +30 delta).
- `scripts/check-ac-state.py --run-tests --ratchet --mandate 1885c8eda` →
  exit 0: 10 ceilings exact, 1 floor exact, all 5 newly claimed ADR-104
  criteria proven, 0 new absent links. ADR-104 carried its own AC-N criteria
  for the first time this round, which removed it from
  `adrs_without_implementing_spec` (32 → 31, back on the inherited ceiling)
  and raised design coverage 42.506 → 42.8609; the raise is banked in this
  round's own note `quality/ac-state-notes/auto-950.json` (a pure floor
  raise; the gate's fold-weakening guard permits nothing else).
- Regression-naming proof for the scope-pairing test: driving the pre-repair
  `lifecycle.py` (git show HEAD:…) through the three exported drivers with
  deliberately mismatched hook/context pairs ran all three hooks
  (`['activate', 'deactivate', 'invoke']`); the repaired drivers raise
  `ScopeMismatch` before any hook code runs, which is what
  `test_lifecycle_drivers_enforce_hook_scope_pairing` pins.

## Validation battery (develop-sync round, heads `3a621dabf` + `3fb6bc516` +
## `9a6a274a1` + `72d561d30`, branch `auto-950`)

Two develop syncs landed in this round: `cd5618223` (the preserved conflict
round — one path, `docs/adr/ADR-INDEX.md`, resolved by keeping both
`ADR-100126-5445` and `ADR-100126-8c2d` in index order) and `c560d4cca`
(fetched after the first merge committed; six further commits touched this
lane's exact surface, so the branch was synced again). The second merge had
three conflicts, each resolved by union rather than side-taking:

- `packages/maistro-core/src/maistro/extensions/__init__.py` (add/add):
  develop's M9-B1 registry persistence (#939/#952) and this lane's M9-A2 SDK
  (#950) both created the package. Resolved to one module docstring covering
  both halves, both import sets, and the sorted `__all__` union (RUF022).
- `packages/maistro-core/src/_vulture_whitelist.py`: both sides' whitelist
  entries and their posture comments kept — M9-A2 context/lifecycle seams and
  M9-B1 store/CLI seams are disjoint.
- `scripts/verify-wheel-imports.py`: the single `"maistro.extensions"`
  CORE_PUBLIC_SURFACE entry kept once, with both halves' rationale merged
  into one comment.

Executed at `72d561d30` (all exit 0 unless stated):

- `uv sync --locked --extra dev`; `uv run ruff check .` (one RUF022 on the
  merged `__all__`, fixed) and `ruff format --check .` (2989 files).
- `RATCHET_BASE_REV=origin/develop uv run python
  scripts/check-ratchet-provenance.py` → exit 0: all ten ratchets flat, base
  `c560d4cca`, citation-status 0 exceptions, enumerations 1 tolerated,
  contract-markers 371=371, promotion-surface/reachability/adr-status-language/
  shell-execution/lifecycle unchanged.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0; 1342 reviewed
  identities → 1342 findings (develop's registry work added four banked
  identities); `unclassified: 0` with the union whitelist.
- `uv run pytest packages/maistro-core/tests -q --ignore=tests/integration`
  → **12854 passed, 938 skipped, 1 xfailed** (develop's registry/CLI suite
  rides in the same directory; both halves' tests pass together).
- `uv run pytest tests/test_check_extension_imports.py
  tests/test_check_reference_extension.py tests/test_check_citation_status.py
  tests/test_verify_wheel_imports.py tests/test_check_enumerations.py
  tests/test_ratchet_base_rev_policy.py packages/maistro-registry/tests -q`
  → 360 passed, 1 skipped.
- `uv run pytest packages/maistro-core/tests/extensions
  packages/maistro-registry/tests -q` → 79 passed.
- `uv run mypy --strict packages/maistro-core/src/maistro/extensions` →
  Success (10 files, SDK + registry halves).
- `scripts/check-extension-imports.py` → ok (1 extension package, public SDK
  only); `scripts/check-reference-extension.py` → ok (isolation fixture:
  reference-greeter builds and tests in a clean environment).
- `scripts/check_enumerations.py`, `check-citation-status.py`,
  `check-adr-index.py`, `check-shipped-surface-truth.py`,
  `check-route-permissions.py`, `check-reachability.py`,
  `check-reachability-dispositions.py`, `check-contract-markers.py`,
  `check-radon-baseline.py`, `check-security-inventory.py`,
  `check-wiring-reads.py`, `check-agent-store-writes.py`,
  `check-doc-links.py`, `check-backlog-consistency.py` → all exit 0.
- `scripts/check-suite-inventory.py` → ok: 15 suites match the recorded
  inventory (the merged baseline carries both halves' extensions tests; this
  note's +30 delta is unchanged — no test added, removed, or renamed).
- `scripts/check-ac-state.py --run-tests --ratchet --mandate 1885c8eda`
  against a live migrated PG (alembic head): first run failed with
  `design_coverage 42.8433 falls below the floor of 42.8609` — the six
  develop commits' newly accepted, not-yet-proven decisions raise the taken
  denominator to 163 (88 at zero), diluting the ratio. The lane's own
  evidence is unchanged (mandate: every declared criterion proven). Re-banked
  this lane's own note (`quality/ac-state-notes/auto-950.json`) from the
  current measurement per the gate's `--bank` path:
  design_coverage 42.8609 → **43.2114**, reproduced on two consecutive runs
  (the 42.8433 reading was a first-run-after-upgrade outlier that did not
  reproduce); every ratcheted counter flat; a pure floor raise vs the
  previous value and vs the inherited base fold; no inherited note edited.
  Residual risk: the floor is a single-machine measurement; a fresh-CI
  container drawing the low outlier would need the same re-bank.

## Validation battery (develop-sync round 2, heads `fecbcc6bb` + `b35e42659`,
## branch `auto-950`)

Second develop sync, resolving the preserved conflict block: a merge of
`626683154` (develop's M9-C2 #1998) had been left in progress with three
unmerged paths, then current `origin/develop` (`a8258ee24`: M9-F3 #2012,
M9-A1 #1982, M9-D2 #2003 + dependabot bumps) was merged on top. Both merges
committed. Resolutions, all union-preserving:

- `extensions/__init__.py`: four-layer union surface (#950 runtime contract,
  #952 registry, #953 activation, #956 resolution). **Name collision**:
  `errors.ExtensionLifecycleError` (#950 hook-failure wrapper) renamed to
  `ExtensionHookError` — the governed-install flow (#952/#953) already
  exports `ExtensionLifecycleError` as the base of `ManifestRejected` et al.
  and is consumed end-to-end by `maistro_server/api/extensions.py` and
  `test_install_lifecycle.py`; the #950 side owns fewer call sites (ADR-104,
  two test files) and was renamed in lockstep. Test count unchanged — no
  test added, removed, or renamed; only the referenced name changed.
- **ADR number collision**: both sides authored "ADR-104". The
  extension-context ADR (authored 2026-10-05, `fb15092f4`) keeps ADR-104;
  the provider-adapter ADR (merged 2026-10-06 via M9-E1) renumbered to
  ADR-105 (`git mv`), with its SPEC-284 governing citation, the 961 lane
  note, ADR-INDEX and CHANGELOG updated. No `@pytest.mark.ac` marker
  referenced the provider ADR (those use `SPEC-284/AC-N`).
- `_vulture_whitelist.py`: both sides' explicit-reference imports kept.

Executed at `4c672507c` (all exit 0 unless stated):

- `uv sync --locked --all-extras` (CI parity; `--extra dev` alone leaves
  `maistro_bootstrap` import-not-found noise in mypy) plus `uv pip install
  -e packages/maistro-evolve` (formal/ imports it; not a workspace member).
- `uv run ruff check .` → all checks pass; `ruff format --check .` → 3043
  files already formatted.
- `uv run mypy --strict packages/maistro-core/src` → Success, 739 files, 0
  issues.
- `uv run pytest packages/maistro-core/tests/extensions/ -q` → **297
  passed** (both halves: #950 conformance/reference-execution and
  #952/#953/#956 install/registry/resolution).
- `PYTHONPATH=packages/maistro-core/src uv run pytest formal/ --timeout=120
  -q` → **663 passed, 1 skipped** (quality.yml's Pillar 2 step, exact args).
- `RATCHET_BASE_REV=origin/develop uv run python
  scripts/check-ratchet-provenance.py` (CI's exact env spelling,
  vulture-ratchet.yml) → exit 0: citation-status 0 exceptions,
  enumerations 1 tolerated → 1 current, promotion-surface 74=74,
  reachability 170=170, shell-execution 3=3, contract-markers 371=371,
  adr-status-language/lifecycle flat, 49 consumers with provenance.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0; **1332 = 1332**
  reviewed identities → findings (exact multiset match; the vulture ledger
  needed no amendment this round — the rename introduced no unbanked
  identity). `check-shipped-surface-truth.py` → ok.
- `uv run python scripts/check-citation-status-provenance.py` (registry.yml
  step) → exit 0, 0 exceptions vs base `a8258ee24`.
- `uv run pyright --outputjson packages/maistro-core/src` +
  `scripts/check-pyright-report.py --baseline 21` → exit 0; 21 errors = the
  21-error baseline, none in `maistro/extensions/`.
- xenon (CI's exact scope incl. `packages/maistro-ext-sdk/src`) → 140 blocks
  ≤ 145 baseline, 0 average violations, none in extensions/.
- `scripts/check-radon-baseline.py`, `check_enumerations.py`,
  `check-doc-links.py` (exercised by the ADR-105 rename),
  `check-release-consistency.py`, `bump_version.py --check`,
  `check-suite-inventory.py` (16 suites match; the merged baseline carries
  both halves' extension tests and the new `maistro-ext-sdk` suite) → all
  exit 0.
- `scripts/check-diff-coverage.py` over a scoped coverage run
  (`pytest packages/maistro-core/tests/extensions/ --cov=maistro
  --cov-branch`, `--base origin/develop`) → all five measured
  `maistro/extensions/*` files plus `maistro/runtime/__init__.py` pass the
  90% line / 80% branch floors; the only absent file,
  `scripts/verify-wheel-imports.py`, is unchanged branch content measured by
  CI's full `coverage-unit` producer, which a scoped run cannot reproduce.
- `scripts/check-ac-state.py --run-tests --ratchet --bank` → measured
  design coverage **38.9049** over 164 taken decisions (89 at zero), banked
  in this lane's own note (43.2114 → 38.9049). The fall is inherited, not
  introduced: base `a8258ee24` itself measures **38.5301** over 163
  decisions (89 at zero; verified in a throwaway worktree) — develop's WIP
  merges added unproven decisions after the M9-E1 note banked 43.2114, and
  no `quality/ratchet-authorizations.json` grant exists at base to disown
  the merged floor. The candidate is above its base (+0.37pp, the lane's own
  ADR-104 evidence); the ratchet's regression half still judges against the
  base-resolved fold, which only a base-side grant or evidence restoration
  can move. Residual risk: until develop re-banks or grants, every branch
  off develop fails the acceptance-state ratchet the same way.

## Validation battery (verification round at head `e1500a6de`, branch
## `auto-950`)

Independent re-verification of the whole battery at the develop-sync round 2
head; no code changed this round. Environment rebuilt to CI parity first
(`uv sync --locked --all-extras`, then `uv pip install radon xenon vulture
pyright interrogate pytest-timeout`, then `uv pip install -e
packages/maistro-evolve` — the same order as quality.yml's quality-gate job).

- `RATCHET_BASE_REV=origin/develop uv run python
  scripts/check-ratchet-provenance.py` → exit 0; base `a8258ee24`, all ten
  ratchets flat (citation-status 0, enumerations 1=1, promotion-surface 74=74,
  reachability 170=170, contract-markers 371=371, adr-status/shell/lifecycle
  flat), 49 consumers with provenance.
- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` → exit 0, **1332 = 1332** (no ledger amendment needed).
- `pytest packages/maistro-core/tests/extensions/ -q` → **297 passed**;
  `pytest packages/maistro-server/tests/api/test_extensions_api.py -q` → 16
  passed (develop-side consumers intact).
- `mypy --strict packages/maistro-core/src` → 0 issues, 739 files; pyright →
  21 errors = baseline 21 (`check-pyright-report.py` exit 0); xenon (CI scope
  incl. ext-sdk/rsi) → 140 blocks ≤ 145, 0 module/average violations;
  interrogate → all 13 package floors pass (maistro/ floor 57.9% ≥ 46%);
  `check-radon-baseline.py` → 138 = 138.
- `pytest formal/ --timeout=120 -q` → 663 passed, 1 skipped; fitness suite →
  23 passed; suite-inventory (`--suite packages/maistro-core/tests`) → ok
  (14339 collected = recorded).
- All architecture/consistency gates exit 0: enumerations, workspace
  retirement, route permissions, principal identity, frontend typed client,
  vendor_ifeval/vendor_bfcl, credential authority, wiring reads, agent store
  writes, contract markers, convergence matrix, reachability +
  dispositions, security inventory, image inventory + pins, workflow
  inventory, backlog consistency, execution lifecycles, model egress,
  foreign-harness egress, shipped-surface-truth,
  citation-status-provenance, m1-convergence-freeze (`--base a8258ee24`),
  adr-index, `bump_version.py --check`, release consistency, doc links,
  `maistro-registry lint . --strict` (435 files), extension-imports,
  reference-extension (clean-environment build).
- `alembic upgrade head` against a live pgvector/pg18 → exit 0 (head `058`).
- `check-diff-coverage.py` with combined coverage (extensions suite +
  `pytest tests/ --source=scripts` producer) and `--base
  d39a2e4ce` (develop tip, CI's PR form) → ok, every measured touched file
  ≥ 90% lines / 80% branches.
- Acceptance-state gate re-run in CI's PR form (`--run-tests --ratchet
  --mandate d39a2e4ce`): the **mandate halves both pass** — 5 criteria added
  or newly claimed, 0 unproven; 0 new chain gaps. The **only** failure line
  remains `design_coverage: 38.9049 falls below the floor of 43.2114`.
- Base re-measurement reproduced with the gate's own base-measurement recipe
  (`git worktree add --detach` at `a8258ee24`, `uv run --project <tree>
  --locked --all-extras python scripts/check-ac-state.py --run-tests`):
  **38.5301% over 163 taken decisions (89 at zero)** — the develop base
  itself sits below the fold's 43.2114 floor, and `git diff --stat
  a8258ee24..origin/develop -- quality/` is empty (the two newer develop
  commits, `3b8e090fe`/`d39a2e4ce`, touch only docs/inventory notes), so no
  develop-side grant or re-bank has landed. The fold at the candidate's base
  is unmeetable at develop; the candidate is +0.37pp above its actual base.
- One environmental note for future rounds: running `check-ac-state.py`
  locally writes the gitignored report `quality/ac-state.json` into the tree,
  and `tests/test_branch_independence_repository.py::
  test_every_quality_json_state_surface_is_classified_once` scans the
  filesystem, so a root-`tests/` run AFTER an ac-state run reports
  `unclassified quality state: quality/ac-state.json`. CI's coverage-unit job
  runs `pytest tests/` on a fresh checkout where the file does not exist; the
  test passes on that state (verified: 1 passed with the generated file moved
  aside). Run root-`tests/` before any local ac-state run, or move the
  generated report aside first.

## Validation battery (develop-sync round 3 at merge `f056443b0`, branch
## `auto-950`)

Third develop sync: `origin/develop` moved to `1e640df17` (M9-J1 #2020
extension catalog, M9-J3 #2017 discovery→observe flow, M9-C3 #2002 upgrade
preflight, plus a first-line-waiver mutation round) — 4 commits, +6029/−3,
touching this lane's exact package (`extensions/catalog_service.py`,
`extensions/preflight.py`, `store.py`, `sqlite_store.py`, `__init__.py`,
`_vulture_whitelist.py`, `container.py`, `cli/_extensions.py`,
`maistro_server/api/catalog.py`). One conflict, resolved by union:
`extensions/__init__.py` `__all__` — develop's `PreflightPolicy` /
`PreflightReport` / `run_preflight` inserted in index order beside this
lane's `ProgressReporter` / `ProgressSink` / `run_activation` /
`run_deactivation` / `run_invocation`; both halves' import blocks had
auto-merged cleanly. No test added, removed, or renamed this round.

Executed at the merge commit `f056443b0` (environment rebuilt to CI parity
first: `uv sync --locked --all-extras`, `uv pip install radon xenon vulture
pyright interrogate pytest-timeout`, `uv pip install -e
packages/maistro-evolve`):

- `uv run ruff check .` → all checks pass; `ruff format --check .` → 3051
  files already formatted.
- `RATCHET_BASE_REV` default (`origin/develop` = `1e640df17`) `uv run python
  scripts/check-ratchet-provenance.py` (vulture-ratchet.yml:77, CI's exact
  step) → exit 0: all ten ratchets flat vs base `1e640df17c8a`
  (citation-status 0 exceptions, enumerations 1 tolerated → 1 current,
  promotion-surface 74=74, reachability 170=170, shell-execution 3=3,
  contract-markers 371=371, adr-status-language/lifecycle flat, 49 consumers
  with provenance). `check-citation-status-provenance.py` (registry.yml:108)
  → exit 0. `check-shipped-surface-truth.py` → ok.
- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` → exit 0; **1332 = 1332** reviewed identities →
  findings. develop's new preflight/catalog code arrived pre-whitelisted
  (`_vulture_whitelist.py` +10, merged cleanly); **no ledger amendment
  needed or made**.
- `uv run pytest packages/maistro-core/tests/extensions -q` → **383
  passed** (this lane's 30 + develop's catalog/preflight/lifecycle-proof
  suites, passing together on the merged `__init__` union).
  `packages/maistro-server` catalog + extensions API + container-wiring →
  31 passed.
- `uv run mypy --strict packages/maistro-core/src` → Success, 741 files
  (739 + develop's 2 new modules), 0 issues. Pyright (CI's exact form:
  `--outputjson packages/maistro-core/src` + `check-pyright-report.py
  --baseline 21 --exit-code <status>`) → **21 = 21**, exit 0.
- xenon (CI's exact scope incl. `maistro-ext-sdk/src`, `-i third_party`) →
  140 blocks ≤ 145 baseline, 0 module-rank, 0 average violations.
  `check-radon-baseline.py` → 138 = 138, exit 0. All 12 interrogate floors
  (quality.yml:1487-1507) → pass.
- `uv run pytest formal/ --timeout=120 -q` (Pillar 2, CI's exact args) →
  **663 passed, 1 skipped**.
- `check-suite-inventory.py --suite packages/maistro-core/tests` → ok:
  14425 collected = recorded (14339 + develop's 86; both lanes' delta notes
  reconcile with no baseline edit this round).
- Acceptance-state gate in CI's PR form (`check-ac-state.py --run-tests
  --ratchet --mandate 1e640df17c8a7dda647afa64d6a97384a93dee78`): both
  **mandate halves pass** — 5 criteria added or newly claimed, 0 unproven,
  0 new chain gaps. The **only** failure line remains `design_coverage:
  38.9049 falls below the floor of 43.2114`, folded from 30 notes at base
  `1e640df17c8a`. The merged tree measures byte-identically to the
  pre-merge round (164 taken decisions, 89 at zero) — the develop sync
  neither helped nor hurt.
- **Base re-measured first-hand this round** (not inherited from the prior
  round's claim): `git worktree add --detach` at merge-base `a8258ee24`,
  the gate's own recipe (`uv run --project <main tree> --locked
  --all-extras python scripts/check-ac-state.py --run-tests`) → design
  coverage **38.5301% over 163 taken decisions** — the develop base is
  below the fold floor too, and below this branch (candidate +0.37pp).
  `git diff HEAD..origin/develop -- quality/` after the sync shows only
  this lane's own branch-owned `ac-state-notes/auto-950.json` difference:
  **no re-bank or `ratchet-authorizations.json` grant has landed on develop
  at `1e640df17` either**, so the two-merge rule still makes a branch-side
  grant inert and the gate's fold-weakening guard still refuses editing the
  inherited note. The remedy remains develop-side: re-bank the diluted
  measurement there (`check-ac-state.py --run-tests --ratchet --bank`,
  justified in that diff) or land a grant, then re-sync this branch.
- Codex PR-review findings (reviewed at `5f5c230`, eight commits back)
  re-checked against current production code: cross-workspace refusal
  (`host.py` routed-dispatch `ScopeMismatch`), outside-Attempt refusal,
  and declared-only composition filtering (`host.py` "keep only
  descriptor-declared entries"), lifecycle scope-pairing
  (`lifecycle.py::_require_scope` in the exported drivers), config
  snapshot/detachment — all present. **Still open** (recorded, not repaired
  this round — they are hardening beyond the banked AC set and do not move
  the gate): extension provenance is recorded only after
  `route.dispatch()` succeeds, so denied/failed effect attempts are not
  attributed to the extension in the governed events (`host.py`
  `_dispatch_effect`); nested configuration values are snapshotted
  shallowly; `ExtensionContext.identity`/`.scope` slots are writable by
  assignment despite `__slots__`.
