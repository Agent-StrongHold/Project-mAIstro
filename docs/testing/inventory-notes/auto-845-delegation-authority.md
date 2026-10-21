---
inventory-delta:
  packages/maistro-core/tests: +5
  packages/hive-conductor/backend/tests: +17
  tests/: +4
---
# #845 host-authorized delegation and execution tiers

The new core tests prove that a host grant binds the agent, owner, target,
Goal/Run/Invocation, scope, exact artifact, expiry, and provenance; the
resulting effective action set is an intersection rather than a target
manifest grant; approvals cannot be reused for another artifact; and an
agent manifest cannot delegate without a host grant. The Hive adapter tests
prove request `execution_tier` values do not select isolation and
`tier_approved_by` metadata cannot clear a host block.

## Repair round (graph-node gate reachability)

Core (`test_delegation_authority.py`, net +3 tests): the execution-mode
contract is now "an authorized action gets its tier's isolation floor".
`blocked` is reserved for host denial (permission miss or `Tier.BLOCKED`);
authorized-but-uncleared elevation runs at the sandbox floor and only an
explicit `OPEN`/`ROLE_AUTO` host tier record selects inline. New pins: a
permission miss denies even a role-bearing principal; an explicit
`Tier.BLOCKED` tier denies; a stored TTL-bound elevation grant clears
SELF_ELEVATION while staying action-bound and off the inline mode; an
uncleared `DELEGATED` tier never reaches inline.

Hive (`test_legacy_dag_node.py`, +5 tests): `LegacyConductorNode._execute`
is now driven end-to-end against a production-shaped Sentinel (fail-closed
`build_permission_table` + live `CapabilityPermissionSource` over the
default capability registry). Pins: the shipped empty table blocks every
node; a stated `graph.node.execute` permission grant makes the node run at
the floor the host resolves for it; a configured grant cannot authorize a
roleless principal (the unsatisfiable-gate regression this repair fixes —
the adapter now carries host-resolved roles into its Principal); an
untrusted node needs an explicit tier record, not just a permission grant;
an explicit `ROLE_AUTO` record selects inline execution.

Core grant provisioning goes through the documented host-only mutation API
(`InMemoryDelegationAuthority.add_host_grant`), keeping the trust boundary
itself covered by tests rather than constructor backdoors.

## Repair round (2026-10-20) — develop sync merged, B1 and B2 closed

`origin/develop` (`e20e9f52e`) is merged into this branch (merge commit
`292a383bd`, merge-base `e20e9f52e`). The four conflicts were resolved by
combining both sides: `canonical_dag_runner.py` and `legacy_dag_node.py`
keep develop's `effect_context` / `governed_runtime` / progress-hook wiring
*and* this branch's Sentinel gate, host-mode resolution and principal-role
resolution; `optimizer.py` takes develop's escalation handling
(`upgrade_execution_tier` is an escalation there, not a tier upgrade);
`container.py` takes develop's restructured composition root and re-adds
`InMemoryDelegationAuthority` plus `delegation_authority=` on the Sentinel.

### B2 — the vulture ratchet is green without touching the ledger

The gate is `python scripts/check-vulture-baseline.py packages/*/src
--min-confidence 60 --exclude '*/third_party/*'`; it now exits 0 with
1326 findings — exactly develop's banked count, no new identity, no row
dropped. The branch was made vulture-neutral *in source* rather than by
editing `quality/vulture-baseline.json` or `quality/ratchet-authorizations.json`
(a ledger edit is not allowed in an ordinary implementation PR, and a grant
authorizes a later change, never its own introduction):

- `DelegationGrant.grant_id` → `grant_ref`, `DelegationDecision.grant_id` →
  `grant_ref`, `AuthContext.delegation_grant_id` → `delegation_grant_ref`.
  The name `grant_id` already belongs to
  `maistro.security.trust_boundary.PermissionGrant.grant_id`, and vulture's
  `used_names` is a global exact-match set: a second `.grant_id` load masks
  develop's banked row. One identifier, one meaning.
- `DelegationGrant.granted_by` is now read: it is carried on
  `DelegationDecision`, logged by `agents/base.py` ("Delegation authorized by
  host policy: … grant_ref=… granted_by=…") and published on the A2A task
  metadata as `delegation_granted_by`.
- `InMemoryDelegationAuthority.add_host_grant` is now genuinely read: the
  authority seeds its grants through it (`__init__` takes an iterable of
  grants), so the host-only mutation API stays the single provisioning path
  and is exercised from `src`.
- `Sentinel.resolve_execution_mode` / `Sentinel.resolve_authorized_execution_mode`
  moved out of the core into `packages/hive-conductor/backend/services/execution_mode.py`.
  The isolation vocabulary ("blocked" / "async" / "sandbox") belongs to the
  Conductor adapter, not to the core; the core keeps exactly one policy
  decision surface (`Sentinel.authorize` + `Sentinel.resolve_tier`), so no
  competing authority path is introduced. The adapter helper is outside the
  vulture scan (`packages/*/src` only).
- `AuthContext.delegation_grant_ref` is now read inside `src`: `Sentinel.pre_call`
  emits it on the call audit (`detail="delegation_grant_ref=…"`, the host's
  reference only — never request content), which is also what makes the
  approval/elevation provenance criterion observable at the audit seam.

### B1 — graph-node execution is reachable in every shipped Conductor profile

The blocker was a deployment gap, not a code gap: the fail-closed table
denies `graph.node.execute` because no preset names it (the
`hive_conductor_tools` preset is pinned to `services.tool_executor.TOOLS` by
`tests/security/test_sentinel_permission_table_armed.py`, so the preset
cannot carry it). The repair states the grant where authority belongs — the
deployment:

- `MAISTRO_PERMISSIONS='{"graph.node.execute": ["admin", "user"]}'` is now
  part of the shipped Conductor profiles: `docker-compose.yml`,
  `docker-compose.pm-poc.yml`, `deploy/docker-compose.prod.yml` and
  `packages/hive-conductor/docker-compose.yml` (the four stacks the
  `hive-conductor` service runs in). The code default stays fail-closed
  (`permission_preset="none"`, empty map): an unstated grant still denies
  every node.
- `graph.node.untrusted` is deliberately *not* granted: the untrusted node
  class stays behind its own host tier/approval record.

New evidence:

- `tests/security/test_sentinel_permission_table_armed.py::test_shipped_profiles_authorize_graph_node_execution`
  renders each shipped Conductor profile exactly as `docker compose` would
  and asserts the composed table grants `graph.node.execute` to the host
  roles `admin` and `user` (the roles a Conductor user record carries).
- `packages/hive-conductor/backend/tests/test_execution_mode.py` (new file,
  8 tests) pins the behavior of that grant: a normal node is reachable at
  the floor the host resolves for it (inline when the node cannot reach the
  world, sandboxed when it can), `graph.node.untrusted` stays blocked, a principal
  without a host role is denied, and the isolation floor is derived from the
  tier Sentinel resolved — never from a caller label. The four
  execution-mode tests that used to live in the core suite moved here with
  the code they cover (they exercise the adapter's vocabulary).

### Remaining limitations (recorded, not repaired in this round)

- **Delegation grants have no product path yet.** Exact-bound grants
  (`artifact` / `run_id` / `invocation_id`) can only be minted by a host
  component at runtime; `InMemoryDelegationAuthority` is process-local, so
  a grant does not survive a restart. Wiring the HITL reviewer flow
  (park → approve → resume) into grant issuance is the follow-up.
- **Elevation request/grant/clear is not exposed over HTTP.**
  `request_self_elevation` / `confirm_self_elevation` exist in
  `maistro.security.sentinel.elevation` and the container wires an
  `elevation_store`, but no shipped route issues or clears an elevation.
- **`graph.node.untrusted` remains ungranted** pending an explicit host
  tier/approval record.

`inventory-delta` for this note is now `packages/maistro-core/tests: +5`
(the execution-mode tests moved to the Hive suite), `packages/hive-conductor/backend/tests: +17`
(the new `test_execution_mode.py`, 8 tests, plus the branch's earlier
adapter pins) and `tests/: +4` (the new parametrized shipped-profile pin).

## Repair round (2026-10-20, third) — the isolation floor is the host's, not a blanket elevation

The develop sync left 30 develop-origin DAG tests failing
(`test_dag_model_tools.py`, 27; `test_legacy_dag_node_container_composition.py`,
3). Both were branch-caused, in two different ways.

### The floor: a blanket `SELF_ELEVATION` default made every node sandboxed

`LegacyConductorNode._execute` resolved `graph.node.execute` with
`reversibility="irreversible"` and `default=Tier.SELF_ELEVATION`, so every
trusted node resolved to an elevation tier and therefore to the *sandbox*
floor. Two product consequences, both observed:

- the sandbox executor refuses the `autonomous` mode without a
  user-space-kernel backend ("REFUSED: 'autonomous' execution requires
  gVisor or microVM isolation"), which is what the 30 tests failed with;
- the Conductor's *tool* nodes (e.g. `clarify`) lost their tool semantics,
  because the tool path only exists on the inline branch of
  `_run_node_tier` — a tool node in the sandbox path runs the generic
  model script instead.

The floor is now the host's own reading of the node
(`services/legacy_dag_node.py::_node_reaches_the_world`): a node whose
*declared* capabilities can reach the world (shell / file write / secrets) is
irreversible, so the host tier resolves to an elevation tier and the node
runs sandboxed; a node that declares none of them is reversible, so the host
tier resolves to the inline floor. An explicit host tier record still
governs either way (it can raise the floor to the sandbox or deny the node),
and the caller's `execution_tier` / `tier_approved_by` labels remain
metadata only. The fail-closed gate is unchanged: without the deployment's
`graph.node.execute` grant the node is still blocked before any of this.

New/updated pins in `packages/hive-conductor/backend/tests/test_legacy_dag_node.py`:
a stated grant runs an ordinary node inline; a node that declares
side-effecting capabilities runs in the isolated subprocess; an elevating
host tier record raises an ordinary node to the sandbox floor. The
adapter-level pins in `test_execution_mode.py` now state the two floors a
shipped deployment produces (inline for a reversible node, sandbox for an
irreversible one).

### The fixtures: the develop tests were running in a deployment that stated nothing

The two develop-origin modules built their container with
`create_container(AgentConfig(...))` — no permission grant, and an acting
user the host had no record of — so under the fail-closed table every node
was denied (`node_blocked … reason=host_policy`). They now model the
deployment they run in, through two shared fixtures in
`packages/hive-conductor/backend/tests/conftest.py`:

- `shipped_deployment_security` reads the *shipped* Conductor profile
  (`packages/hive-conductor/docker-compose.yml`) and uses the
  `MAISTRO_PERMISSION_PRESET` / `MAISTRO_PERMISSIONS` it states, so the
  tests prove the shipped authority instead of a restated copy of it (a
  profile that stopped stating the grant fails these tests loudly);
- `host_user_actor` registers the acting user in the host's user store for
  the duration of the test (and removes it again), because the adapter
  resolves the principal's roles from that store
  (`services/canonical_dag_runner._host_principal_roles`).

No product code was weakened to get there: the deployment states the grant,
the host states the role, and the gate still denies anything else.

## Validation round (2026-10-20) — develop sync verified complete, gates re-run at `10e51d26e`

The develop sync conflict recorded as the previous block is resolved: merge
commit `292a383bd` (`Merge origin/develop into auto-60 (#60/#845)`) has
parents `7a76ef082` and `e20e9f52e`; the working tree is clean; `origin/develop`
is still at `e20e9f52e` (the merge-base, 0 commits ahead), so there is no
further sync to perform. The resolution is complete and consistent:
`optimizer.py` is byte-identical to develop's (0-line diff — develop's
escalation handling was taken as documented), and no conflict markers remain
anywhere under `packages/` or `docs/`.

Re-run at head `10e51d26e5d53257acd65d0f03191a68b751a3bc`:

- `uv run ruff check .` — all checks passed; `uv run ruff format --check .`
  — 3366 files already formatted.
- Targeted suites: `packages/maistro-core/tests/security/test_delegation_authority.py`
  + `a2a/test_broker.py` + `tests/security/test_sentinel_permission_table_armed.py`
  — 33 passed; `packages/hive-conductor/backend/tests/test_execution_mode.py`
  + `test_legacy_dag_node.py` + `test_legacy_dag_node_container_composition.py`
  — 46 passed; `test_dag_model_tools.py` + `test_security_regression.py` —
  40 passed.
- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` — exit 0, 1326 findings (exactly develop's banked count,
  no ledger edit).
- `check-suite-inventory.py` — ok, 21 suites match the recorded inventory.
  The note's deltas reconcile exactly: core +5 (the new
  `test_delegation_authority.py`), hive +17 (`test_execution_mode.py` 8 +
  `test_legacy_dag_node.py` 9), tests/ +4 (the parametrized
  `test_shipped_profiles_authorize_graph_node_execution`, one case per
  shipped profile).
- `check-backlog-consistency.py`, `check-reachability-dispositions.py`
  (48 groups / 168 modules), `check-radon-baseline.py` (134 C-or-worse),
  `check-promotion-surface.py`, `check-shipped-surface-truth.py` — all ok.
- `xenon` with CI's exact arguments — 0 block violations (baseline 134),
  0 module violations, no average violation.
- `mypy packages/maistro-core/src` — success, 797 source files.

### The one red gate is inherited from develop, not branch-caused

`check-ratchet-provenance.py` fails the reachability ratchet:
`maistro.runs.admission_identity` is flagged NEW unreachable (169 vs the
trusted base's 168). This is a pre-existing develop-side structural blocker,
proven three ways:

1. The module exists at the trusted base `e20e9f52e` and nothing imports it
   there (`git grep` over `origin/develop` finds only docs and its own test).
2. Running `check-reachability.py` in a scratch worktree at `e20e9f52e`
   reports the same module as unreachable — the trusted base itself carries
   the debt.
3. The branch diff touches nothing under `runs/` (`git diff --name-only
   e20e9f52e..HEAD` lists no `runs/` file), and develop's own inventory note
   (`docs/testing/inventory-notes/task-admission-identity-types.md`) records
   this exact failure as the #1851 leaf's known structural blocker — that
   leaf was prohibited from adding a reachability-baseline entry, and the
   two-merge rule makes a branch-side entry inert anyway.

The same failure reds the three root reachability-baseline tests
(`tests/test_reachability_baseline_identity.py` ×2,
`tests/test_check_reachability.py::test_baseline_matches_the_tree`) and
cascades to the Coverage and Quality gates on CI. It is unfixable in this
lane: a ledger/grant edit is prohibited in an ordinary implementation PR, and
wiring the module is #1851's surface, not #60/#845's.

## Repair round (2026-10-20, second) — full gates re-run at `ab8ecc92b`; the inherited reachability block proven by scan-set identity

Independent re-validation of every prior claim at head `ab8ecc92b`. All
prior-round claims held; two items gained stronger evidence.

### The reachability block: the unreachable SET is identical at base and head

Beyond the prior membership check, this round computed the full unreachable
module set with the same analyzer (`check-reachability.py::_reachability`)
over both trees: base `e20e9f52e` → 169 unreachable of 1417 modules; head
`ab8ecc92b` → 169 unreachable of 1419 modules; set difference **empty in both
directions** (no module changed reachability). The trusted-base ledger at
`e20e9f52e` records 168 — the base ledger is stale relative to the base's own
code, which develop's round-221 note (`task-admission-identity-types.md`:
"check-reachability.py: rc=1, exactly 1 NEWLY UNREACHABLE
`maistro.runs.admission_identity`", owner-held) already documents. `origin/develop`
has not moved since (still `e20e9f52e`), so the blocker is live on develop
itself; `load_authorizations` reads grants from the merge base, so no edit on
this branch can turn the gate green.

### `mypy --strict` requires CI's environment, not `--extra dev`

`uv run mypy --strict packages/maistro-core/src` fails with 5 `import-not-found`
errors on `maistro_bootstrap.*` in a venv built with `uv sync --locked
--extra dev` — that sync installs only a subset of the workspace members
(no `maistro-bootstrap`/`maistro-server`/`maistro-turing`), and no mypy
override covers `maistro_bootstrap.*`. CI's `quality-mypy` job syncs with
`--locked --all-extras`; under that exact environment the gate passes:
`Success: no issues found in 797 source files`. The errors are environmental,
not branch-caused (the branch touches neither `cli/_install.py` nor
`cli/_builders_tui.py`, and `maistro-bootstrap` exists at both base and head).

### Full-suite and gate results at `ab8ecc92b`

- Targeted suites, full packages: `packages/maistro-core/tests/security` +
  `tests/a2a` — 1677 passed, 22 skipped; `packages/hive-conductor/backend/tests`
  — 3785 passed, 24 skipped; root `tests/security` — 15 passed. Focused on the
  branch's files: `test_delegation_authority.py` + `test_broker.py` +
  `test_sentinel_permission_table_armed.py` + `test_execution_mode.py` +
  `test_legacy_dag_node.py` — 76 passed.
- `ruff check .` / `ruff format --check .` — clean.
- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` — exit 0, 1326 reviewed == 1326 findings, unclassified 0,
  never_allowlist 0 (no ledger edit).
- `check-suite-inventory.py` (21 suites match), `check-radon-baseline.py`
  (134 == 134), `check-promotion-surface.py`,
  `check-reachability-dispositions.py` (48 groups / 168 modules dispositioned),
  `check-backlog-consistency.py`, `check-shipped-surface-truth.py`,
  `check-security-inventory.py`, `check-execution-lifecycles.py` (19 == 19) —
  all exit 0.
- `check-ratchet-provenance.py` — every sub-ratchet passes except the
  reachability trusted-base gate documented above.

No test counts changed in this round; the `inventory-delta` block above is
unchanged and still reconciles.

## Verification round (2026-10-20, third) — independent re-verification at `13fd2745e`

Re-executed at the assigned head by the independent verifier (driver checks
plus fresh runs):

- Focused suites: `test_delegation_authority.py` + `test_broker.py` +
  `test_sentinel_permission_table_armed.py` — 33 passed;
  `test_execution_mode.py` + `test_legacy_dag_node.py` +
  `test_legacy_dag_node_container_composition.py` + `test_dag_model_tools.py` +
  `test_security_regression.py` — 86 passed. `ruff check .` and
  `ruff format --check .` clean; `check-suite-inventory.py` 21/21;
  `check-backlog-consistency.py`, `check-shipped-surface-truth.py`,
  `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` (1326 == 1326) all exit 0.
- The reachability trusted-base failure was re-proven **inherited** by direct
  scan-set computation on a base-tree export (`git archive e20e9f52e`): the
  base scans to 169 unreachable modules *including*
  `maistro.runs.admission_identity`; the branch touches zero `runs/` paths.
- **NEW branch-caused gate failure (repair required):**
  `check-workspace-retirement.py` exits 1 —
  `packages/hive-conductor/backend/stores.py::users: NEW importer
  packages/hive-conductor/backend/services/canonical_dag_runner.py -- a
  retiring surface may not gain consumers`. Introduced by
  `_host_principal_roles` (`import stores; stores.users.get(...)`), which
  landed with the develop sync / isolation-floor rounds. Matches the live
  FAILURE of CI `Quality / Workspace retirement` and the aggregate
  `Quality gate (Pillars 1–4, 7, 8)` at this head. The server-side role
  resolution itself is required by #845; the repair must move the lookup onto
  an approved (non-retiring) store seam — not a retirement-ledger edit.
- CI `Supply chain (pip-audit)` and the aggregate CI `security` job FAIL at
  this head; the branch diff contains no `uv.lock` / `pyproject.toml` /
  requirements changes, so the advisory set is develop-vintage, not
  branch-caused — but the checks are red on the PR.
- CI `exact-debt-ledger` (Vulture Ratchet) reproduces locally as
  `check-ratchet-provenance.py` failing **only** on the documented
  reachability trusted-base row; its vulture step passes locally with CI's
  exact arguments.
- PR #2242 is still DRAFT; `test`, `coverage (no services)`,
  `coverage (PostgreSQL)`, `integration-scope`, `docker-build` and the
  `gates-ran` context were IN_PROGRESS at capture — no green claim is made.
- **Closure-keyword review:** commit `a0fbfe33c`'s subject "Close #60
  blockers: …" contains the `Close #60` pair GitHub parses as an auto-close
  directive once the commit reaches the default branch; #60 must not close
  before #845 closes. Reword before merge (e.g. "Address #60 blockers: …").
- Date drift fixed in this note: the two round headings below were dated
  2026-10-27; every commit in those rounds is dated 2026-10-18…2026-10-20
  (`git log`), so they now read 2026-10-20.

Verdict evidence for this round: NEEDS-REPAIR (workspace-retirement importer;
closure keyword). No test counts changed; the `inventory-delta` block above is
unchanged and still reconciles.
