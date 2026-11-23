# REPAIR-NOTES-2469 — independent verification round (branch auto-2469)

Job: repair/verify round for issue #2469 in `/home/dev/Git/wt/auto-2469`, branch
`auto-2469`, exact head `cd242926cad72134ad8480924c62ea971106e06f`, base
`c87dd79acd2a0df83ad2030e18613259899bcd14`. The two lane commits
(`0a1d48fda2` gate + tests, `cd242926ca` durable legs) were verified
end-to-end this round; **no code changes were needed**. The immediately
prior attempts failed on a provider outage before running any checks
(`checks: []` in the prior result artifact), so this is the first round with
executed evidence.

## Verdict

MERGE-READY (writer handoff — this is validation evidence, not integration
approval). All executable acceptance criteria proven against reachable
production behavior at the exact head; one interpretation note and one
residual risk documented below.

## Executed evidence

### Acceptance 1 — reads disclose only the caller's membership universe
- `packages/hive-conductor/backend/tests/test_optimizer_workspace_authorization.py::test_global_list_discloses_nothing_cross_tenant` —
  A's `GET /v1/optimizer/proposals` returns only A's ids; B's proposal ids,
  rationale, and DAG id appear nowhere in the response blob; unprivileged
  principal (no Workspace) sees `[]`. Also
  `test_dag_list_refuses_foreign_and_unknown_dags_identically` — foreign and
  unknown per-DAG lists share one indistinguishable 404.
- All green: 77 passed / 1 skipped (the skip is the PG durable leg without a
  DSN — run separately below).

### Acceptance 2 — foreign decision writes nothing
- `test_foreign_decision_is_404_and_writes_nothing` — A's accept/reject on
  B's proposal: 404, stored row byte-identical (`decision` still `pending`,
  no `decided_by`/`decided_at`), zero `optimizer_decision` audit entries, zero
  template versions (no candidate/promotion).
- `test_viewer_member_can_read_but_not_decide` — a live member without write
  authority can read (200) but decisions answer 403.

### Acceptance 3 — owner decision + revocation
- `test_owner_decision_promotes_with_real_actor_and_canonical_tenant` — B's
  accept: 200, `decided_by` = B, promotion under the gate-resolved tenant
  (version 1 active), audit names B as decider and promoter, descriptor
  surface synced, and version 99 correctly absent from the lifecycle.
- `test_revoked_member_loses_access_with_valid_session` — revocation through
  the canonical authority closes all surfaces while the session/elevation
  stay valid.

### Acceptance 4 — runs cannot cross tenants
- `test_run_refuses_foreign_dag_without_execution_or_proposals` — A running
  B's claimed DAG under A's workspace: 404, `execute_dag` spy records zero
  executions, no proposals in A's workspace, descriptor unchanged, zero new
  `optimizer_run` audit rows; absent descriptor shares the same 404.
- `test_run_rejects_a_project_from_another_tenant` — foreign `project_id`
  refused 403 by the selection seam.
- `test_owner_run_still_executes_and_claims_the_dag` — legitimate owner path
  preserved.

### Acceptance 5 — aliasing
- `test_forged_workspace_field_freezes_the_surface` — a forged row rebranded
  into A's tenant freezes the DAG's whole surface for everyone (no rehoming);
  removing the forgery restores the honest surface.
- `test_registration_contradicting_the_recordings_is_refused` — a foreign
  registration contradicts the recordings: lists, decisions, and runs all
  refuse; nothing rehomes onto either tenant.
- Defense in depth verified in `services/optimizer.py::record_decision` — the
  promotion refuses (KeyError → 404) when the authorized tenant contradicts
  the stored recording, so the gate-resolved tenant is what any promotion
  commits into.

### Acceptance 6 — real middleware + durable canonical stores
- The 16 ASGI cases drive `TestClient(main.app)` through the real
  AuthMiddleware (login + elevate for the second principal) against the
  canonical Workspace/Project authority and the canonical template store.
- `test_optimizer_scope_durable.py` — **executed this round against real
  databases**: SQLite leg and PostgreSQL leg both PASS
  (`MAISTRO_TEST_PG_DSN=postgresql://maistro:…@127.0.0.1:18997/maistro`,
  freshly booted `pgvector/pgvector:pg18`, `alembic upgrade head` → 068).
  The gate resolves the owning Workspace from the wired canonical store and
  template store across a full process restart, with a revocation written
  before that restart. (Note: commit message said head 069; current develop
  lineage head is 068 — migration state matches `alembic current`.)
- Negative tests assert zero writes (proposal store, descriptor store, audit
  trail, template versions) — not just HTTP status. Egress: the gate refuses
  before `run_optimizer` is reachable (the `optimizer_run` audit row is only
  written after minting, and none appears), so no provider call path executes.

### Acceptance 7 — mutation control + CI
- `test_gate_removal_flips_the_refusal` (5 parametrized endpoints) — with the
  gate bypassed at its single seam, every one of the five endpoints answers
  the cross-tenant request 200 (lists leak B's rows, decisions carry
  `decided_by=admin`, runs mint A-tenant proposals over B's DAG): removing
  `services.optimizer_scope` makes the suite fail endpoint by endpoint.
  Executed: 5 passed.
- Red-before premises confirmed from git at base `c87dd79acd`:
  `routes/optimizer.py` listed via unscoped `list_proposals`, decided via
  bare `record_decision(proposal_id, …, actor=actor)`, and ran on
  `authorize_hive_dag_scope` for the selection only.
- Single authorization door: no other caller reaches `record_decision`; the
  only other `list_proposals` consumer (`services/attention.py`) is guarded
  by `is_member` before scoping and is not one of this issue's five surfaces.

### Gates (CI-exact arguments where applicable)
- `uv run ruff check .` — pass; `uv run ruff format --check .` — 3631 files formatted.
- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` — 1221 reviewed identities, no delta.
- `check-radon-baseline`, `check-route-permissions` (42 declared, 0 tolerated undeclared),
  `check-principal-identity`, `check-api-route-contracts`, `check_enumerations` +
  `check-enumerations-provenance`, `check-frontend-api-routes`, `check-reachability`,
  `check-wiring-reads`, `check-agent-store-writes`, `check-contract-markers`,
  `check-shipped-surface-truth`, `check-suite-inventory` (21 suites match),
  `check-ratchet-provenance`, `check-public-routes` (optimizer GETs not public),
  `check-security-inventory`, `check-doc-links` — all pass.
- Full `uv run pytest packages/hive-conductor/backend/tests -q` — **4357 passed, 47 skipped**.

## Interpretation note (recorded assumption)

Acceptance 4's "Also reject missing registered ownership" is implemented as:
a `dag_id` with **no descriptor** refuses (404, tested). A descriptor that
resolves to **no registration and no recorded proposals** remains claimable
by the first authorized optimizer run — the canonical bootstrap mechanism
(`POST /v1/dags` records no tenancy; the first run records the authorized
tenant on its proposals; the decision registers the template). This is
deliberate and pinned by `test_owner_run_still_executes_and_claims_the_dag`;
refusing unclaimed runs would make the create→optimize flow impossible for
every tenant, and the pre-existing DAG routes (`GET/PUT /v1/dags/{id}`) are
themselves unscoped, which dominates the residual below. Per-row and
per-surface failures stay fail-closed (scope-less rows visible to no one,
scope-less decisions refused); only the bootstrap claiming is permissive.

## Residual risk (documented, not repaired — outside this issue's five endpoints)

An authenticated principal who learns a **fresh, never-optimized** DAG's id
could claim its optimizer surface into their own tenant by running first
(the id is uuid4, and full descriptor content is already readable by any
authenticated caller through the pre-existing unscoped `GET /v1/dags*`
routes, so this adds no new disclosure). Subsequent acceptance would sync the
descriptor — but descriptor read/edit via the DAG routes is equally unscoped
today. This belongs to the DAG-surface tenancy issues (#766/#364 lineage),
not the optimizer gate; fixing it here alone would shift the hole, not close
it.

---

# REPAIR ROUND 2 — CI gate repair at head 67f06b4fa510 (post-merge of develop c810c956)

The merge-queue evaluation at `67f06b4fa510` failed four check-runs: `test`,
`Quality / Workspace retirement` (+ its dependent `Quality gate (Pillars
1–4, 7, 8)`), and `Coverage gate (publish-set floor + diff coverage)`.

## Root cause (one, with two consequences)

`services/optimizer_scope.py` imported `stores` and read
`stores.optimizer_proposals` / `stores.dags` directly. Both are RETIRE
entries in `quality/workspace-retirement.json`, whose importer lists are
judged against the trusted merge base and may only shrink: the module was a
NEW importer of each store, so `check-workspace-retirement.py` failed, so
`tests/test_check_workspace_retirement.py` failed in the root suite (which
the `test` job and the coverage gate's `--source=scripts` producer both
run), cascading into `Quality gate` and `Coverage gate`. Adding
`optimizer_scope.py` to the importer lists is not an available repair: that
loosening needs a grant landed at the merge base first (RATCHET-PROVENANCE
two-merge rule), and none exists.

## Repair

1. **Storage seam (#2469 unchanged in behavior).** Added three read-only,
   late-bound accessors in `services/optimizer.py` — the module the
   retirement ledger already names as the tolerated consumer of both
   stores — `proposal_rows()`, `stored_proposal(id)`, `dag_known(id)`;
   `services/optimizer_scope.py` no longer imports `stores` at all. Every
   row lookup, page walk, and descriptor existence check is delegated
   through that seam; the ledger's importer lists are unchanged (78 → 78
   tolerated importers) and the routes still hold no import of the
   projection: `optimizer_scope` remains the one authorization door.
2. **Diff-coverage floor.** With the root-suite cascade fixed, the coverage
   gate proceeds to the per-file diff-coverage floor, which flagged 16
   partial branch arcs in `optimizer_scope.py` plus `optimizer.py:682`
   (`record_decision`'s authorized-tenant-vs-recording contradiction raise)
   — all fail-closed edges no route-level test can reach single-threaded.
   New `test_optimizer_scope_refusal_edges.py` (12 tests) pins them: blank
   ids, an unreadable/tenant-less template version, garbage and blank
   projection rows, one template registered under two Workspaces, a row
   contradicting the precomputed DAG tenancy, `_member_role` blank
   identities, decision-filtered paging, an unclaimed DAG's empty list,
   decision on a blank-DAG / deleted-DAG / scope-less row, and the
   `record_decision` contradiction. Every case asserts zero writes.

## Executed evidence (this round, exact head under repair)

- `uv run python scripts/check-workspace-retirement.py` — **OK: 89 entries
  match the tree** (was FAIL with the two NEW-importer findings).
- `tests/test_check_workspace_retirement.py` — 20 passed (was 1 FAILED).
- Root suite `REQUIRE_AUTH=false MAISTRO_DRY_RUN=1 pytest tests/
  --ignore=tests/tools/registry -q` — **5909 passed, 140 skipped, 0 failed**
  (CI's `test` job and coverage gate both red on this suite before).
- Full hive suite under branch coverage — **4369 passed, 47 skipped**; then
  `scripts/check-diff-coverage.py coverage.xml --base c810c956785b` — **ok:
  every measured file ≥90% lines / ≥80% branch arcs**.
- Durable gate legs with a real server: `MAISTRO_TEST_PG_DSN` against the
  lane's `pgvector/pg18` container at `alembic` head 068 — **2 passed,
  0 skipped** (the PG leg really ran; sqlite + postgres).
- `scripts/check-suite-inventory.py` — all **21 suites match** the recorded
  inventory (note `2469-refusal-edge-tests.md` records the +12 delta).
- `uv run ruff check .` / `uv run format --check .` — pass; vulture with
  CI's exact arguments — 1221 reviewed identities → 1221 findings, exit 0.
- Acceptance-criteria tests from round 1 all still pass (disclosure scoping,
  foreign-decision zero-write, owner promotion, revocation, foreign run with
  no execution, project-tenant refusal, forged-field freeze, registration
  contradiction, five-endpoint gate-removal mutation control).

The `##[error] raise RuntimeError('Event loop is closed')` annotations in
the CI `test` job are `PytestUnhandledThreadExceptionWarning` text from the
`packages/maistro-server/tests` producer step — a step that PASSED (the job
continued through it), in a package this branch does not touch; they are not
failures and not caused by this change.

## Round 3 — merge-queue format + inventory repair (head 48bf0bc9a29d)

The merge-queue evaluation of 48bf0bc9a29d failed two checks:

1. `ruff format --check .` — the two outage-refusal tests added in
   48bf0bc9a2 used a non-canonical dict-literal style. Reformatted
   `test_optimizer_scope_refusal_edges.py` (whitespace only; the file's 14
   tests re-run green).
2. `scripts/check-suite-inventory.py` — suite `packages/hive-conductor/backend/tests`
   expected 4416, collected 4418 (net +2): the same two outage tests were
   added without recording their delta. Note `2469-refusal-edge-tests.md`
   amended +12 -> +14 with the outage legs named in the prose. Scoped gate
   now passes: 4418 collected = recorded inventory.

## Executed evidence (this round)

- `uv run ruff check .` — All checks passed.
- `uv run ruff format --check .` — 3632 files already formatted.
- `python3 scripts/check-suite-inventory.py --suite packages/hive-conductor/backend/tests`
  (the verifier's scope) — ok: 1 suite matches the recorded inventory,
  4418 unique node IDs, 0 duplicate evidence.
- 4-suite optimizer battery (`test_optimizer_workspace_authorization.py`,
  `test_optimizer_scope_refusal_edges.py`, `test_optimizer_scope_durable.py`,
  `test_optimizer.py`) — 91 passed, 1 skipped (the PG leg skips without
  `MAISTRO_TEST_PG_DSN`; round 2 ran it green against a real server).
- `test_gate_removal_flips_the_refusal` — 5 passed (gate bypassed at its
  one seam: global list, DAG list, accept, reject, and run all leak, so
  gate removal fails the suite, endpoint by endpoint).
- `uv run python scripts/check-workspace-retirement.py` — OK: 89 entries
  match the tree; importer lists unchanged (78 -> 78).
