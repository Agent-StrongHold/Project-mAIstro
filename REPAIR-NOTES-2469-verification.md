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
