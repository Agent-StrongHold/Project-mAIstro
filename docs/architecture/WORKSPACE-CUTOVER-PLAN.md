# Workspace Cutover Plan

**Status:** draft for review — planning surface, not a decision record (no registry front matter on purpose)
**Owners:** #1046 (Adaptive Workspace), #804 (Persistent Workspace Agent), #53 (Conductor onto Conduit + canonical Runs), #65 (Workspace-centric inspection), #82 (Workspace backlog)
**Companion policy:** [M1-CONVERGENCE-FREEZE.md](M1-CONVERGENCE-FREEZE.md) · [CONVERGENCE-MATRIX.md](CONVERGENCE-MATRIX.md) · [KNOWN-GAPS.md](../../KNOWN-GAPS.md)

## Why this document exists

The Conductor UI is the third attempt at a product surface, and the flaws it carries are
not in its pages. They are in the seams every attempt rebuilt: a per-app principal, a
hand-maintained permission map, hand-typed response shapes, an in-memory audit trail, and a
composition root that constructs its own fallbacks. The Workspace (#1046/#804) is the
fourth attempt. It only deprecates the previous three if its exit criteria say, mechanically,
that those seams are gone — otherwise it inherits them.

The pattern to avoid is already on record: #56 closed by PR keyword while its own closeout
audit said it must stay open; #58 closed with AC-1 unmet (#1078); the credential-routing
seam shipped with zero runtime consumers. A seam that lands is not a cutover. A cutover is
when the old authority can no longer win.

Two rules follow from the freeze policy and are the spine of this plan:

1. **Contract before surface.** No Workspace Home, Attention, or Agent surface is built on
   the current route table, principal dict, or hand-typed client. Phase 0 lands first.
2. **Parity, then delete, ledger-enforced.** Every legacy page, router and store is listed
   with a disposition and a delete-by milestone; the ledger only shrinks; nothing new may
   import a listed module. Same mechanism as `quality/model-egress.json`.

## What the cutover deprecates, and what it does not

The 2026-09-08 architecture review found nine structural problems with no open owner. They
split cleanly:

| Deprecated by the cutover (this plan owns) | Needs its own owner (this plan only depends on it) |
|---|---|
| J — frontend has no typed contract (75 hand-typed entities, 67 raw `fetch`) | A — canonical effect ledger is in-memory on every backend (`container.py:1443`) |
| C — Conductor route table is default-allow (18/37 routers unscoped) | B — three flat-layout apps collide on `config`/`main`/`middleware`/`routes` |
| D (Conductor half) — `request.state.user` dict, `"dags.write"` vocabulary | D (Turing/canvas halves), the unwired core `AuthProvider` framework |
| E (Conductor half) — `log_audit` writes to an in-memory `JsonStore` | F — PostgREST vs asyncpg persistence, SQLite/Alembic schema parity |
| G — `EngineService` fallback registries/stores, if Conductor's backend routes retire too | H — governance cost, `Literal`-status blind spot in the lifecycle checker |
| The 29 Conductor pages and the in-memory `stores.py` dicts | Warden absent from A2A inbound, RSI harvest, Turing backend (#66 in principle) |

A and F are prerequisites, not scope: the Workspace Agent's Invocation records (#804) and
the Home projections (#1048) are only durable if the ledger and the Conductor's persistence
are. They get issues of their own (§7) and Phase 0 blocks on A.

## Phase 0 — the contract (blocks every #1046 child)

Each item is an invariant with a check that is **red on develop today** and must be green
before the item closes. Land the check first, failing, with a baseline; then make it pass.

### P0.1 One principal

**Invariant.** Exactly one principal type crosses a service boundary. It lives in
maistro-core, carries `user_id`, `roles`, `scopes`, Workspace memberships and the ADR-068
scope axes, and every HTTP service constructs it at its auth boundary.

**Today.** `maistro_server.api.principal.AuthenticatedPrincipal` (roles only),
hive `HiveUser` → `request.state.user` dict (`middleware/auth.py:296`), Turing
`dict` **or** `ServiceIdentity`, canvas `CurrentUser`, core `AuthContext`, core `UserInfo`.
maistro-server bridges by hand at `api/chat_completions.py:187`.

**Check.** `packages/maistro-core/tests/fitness/test_principal_identity.py`: AST scan of
`packages/*/src` and `packages/hive-conductor/backend` — any route handler, middleware or
service reading `request.state.user[...]`, or any class named `*Principal`/`*User`/
`*Identity` with a `role`/`roles` attribute outside `maistro.identity.principal`, fails.
Baseline ledger `quality/principal-identity-baseline.json`, ratchet to zero.

**AC text (for #53).** "AC-P1: every authenticated request in maistro-server, hive-conductor
and the Turing backend yields one `maistro.identity.Principal`; no handler reads a
dict-shaped user; the fitness ledger is empty."

### P0.2 One permission vocabulary, default-deny route table

**Invariant.** Every registered router prefix has either a declared permission or a declared,
reviewed reason it has none. Unmatched is denied, not allowed. One vocabulary
(`scope.verb`) is shared by the middleware, `Principal.scopes`, and Binding `policy_refs`.

**Today.** `middleware/auth.py:377-380` returns `None` for unmatched prefixes and
`dispatch` forwards; 18 routers (`/v1/tasks`, `/v1/memory`, `/v1/quotas`, `/v1/work-items`,
`/v1/program`, `/v1/dag-runs`, …) have no entry; `endswith("/invoke")` and
`endswith("/feedback")` exempt any future route with that suffix (#403 covers `/invoke`).
`PrivilegeMiddleware` is a no-op.

**Check.** Extend `scripts/check-public-routes.py` (already bound to this middleware) with a
second registry, `quality/route-permissions.json`: every prefix from `app.routes` must
appear with a permission or an `exempt_reason` + owner + expiry, exactly the shape
`quality/public-routes.json` already uses for unauthenticated paths. Suffix exemptions are
listed as exact paths, not suffixes. Baseline = today's 18; ratchet to zero exemptions
without an expiry.

**AC text (for #53 / #373).** "AC-P2: `check-public-routes.py` proves every registered
Conductor route is either scoped, public-by-declaration, or exempt-by-declaration; an
undeclared route fails CI; `PrivilegeMiddleware` is deleted or enforces its table."

### P0.3 Typed API contract, one client

**Invariant.** Frontend types for backend entities are generated from the backend's
OpenAPI document and nowhere else. All HTTP goes through one client module. A schema
change is a build failure, not an `undefined`.

**Today.** No codegen; 75 hand-written `interface`/`type` in `pages/` + `components/`;
`Agent` typed three ways (`Agents.tsx:20`, `DagBuilder.tsx:49`, `Topology.tsx:6`);
67 raw `fetch(` outside `lib/api.ts` (`Dashboard.tsx` alone has 15 and never imports the
client); `check-frontend-api-routes.py` proves path+method only.

**Check.**
- CI step: `python -c "from main import create_app; ..."` dumps `openapi.json`;
  `openapi-typescript` generates `frontend/src/api/types.gen.ts`; `git diff --exit-code`
  on the generated file.
- ESLint `no-restricted-syntax`: `fetch(` outside `src/lib/`; `interface`/`type` in
  `src/pages`, `src/components` whose name matches a schema component name. Baselines: 67
  and 75, `--max-warnings` replaced by the ratchet.
- `check-frontend-api-routes.py` gains request/response shape: the generated client is
  the only call site, so path+method+schema is one check.

**AC text (for #1048).** "AC-P3: Workspace Home and every surface it composes import
backend entity types only from `types.gen.ts` and call only the generated client; the
raw-fetch and hand-typed-entity ledgers are empty."

### P0.4 One durable audit store

**Invariant.** Authentication, elevation, HITL settlement, tool-policy verdicts and
capability policy decisions land in one durable, queryable audit store keyed by
`Principal.user_id`, Workspace and Run.

**Today.** Sentinel `AuditLog` (`PgAuditLog`/`SqliteAuditLog`, `container.py:1610-1622`)
and hive `log_audit` → `stores.audit_log` `JsonStore` (in-memory unless mirrored) never
meet; login/elevation failures exist only in the JsonStore (`routes/auth.py:770-833`);
`_mutate_hitl` emits nothing; tool verdicts are written to two disconnected stores.

**Check.** `packages/hive-conductor/backend/tests/test_audit_convergence.py`: a failed
login, an elevation, a HITL cancel and a denied tool call each produce one row readable
through the core `AuditLog` on the configured backend; `routes/audit.py` reads from it;
`stores.audit_log` is deleted (retirement ledger).

**AC text (for #53 / #325).** "AC-P4: `GET /v1/audit` is served from the core audit store;
`log_audit` is a thin adapter over it; auth and HITL events are present after restart."

### P0.5 Backend-selected effect context (depends on A)

**Invariant.** On a `postgresql://` or `sqlite:` configuration the Container's
`capability_effects` uses the durable Binding/Invocation/Approval stores; in-memory only on
`memory://`. One effect context per process — `default_effect_context()` is the Container's
instance, not a second `lru_cache`d one.

**Today.** `container.py:1443 capability_effects = new_in_memory_effect_context()`
unconditionally; `approval_store=None`; `SqliteInvocationStore`/`SqliteApprovalStore` exist
with no constructor call; no PostgreSQL implementation.

**Check.** `packages/maistro-core/tests/test_container_postgres.py` sibling asserting the
store classes by backend; `test_effect_context_identity.py` asserting
`default_effect_context() is container.capability_effects`.

**AC text (for #804).** "AC-P5: a Workspace Agent Invocation survives process restart and is
visible from a second replica; the approval it requested is reused, not re-requested."

### P0.6 The Workspace app is a package

**Invariant.** New Workspace backend code lives in an importable package
(`hive_conductor/` or a new `maistro_workspace/`), never as new top-level `routes`,
`config`, `middleware`, `main`, `state` modules.

**Today.** hive-conductor and the Turing backend both define those names; the Turing
suite can never join the one-process CI step; `conftest.py` files carry `sys.path`
surgery. The full rename is B's owner's decision; this plan only forbids growing the
problem.

**Check.** `scripts/check-cross-package-imports.py` rejects a new top-level module under
`packages/*/backend/` that is not inside a package with `__init__.py`.

## Phase 1 — build the Workspace on the contract

The #1046 children (#776, #1047–#1051) and #804/#805/#806 proceed **only** through P0
seams. Each PR that adds a Workspace surface must, in the same PR:

- consume canonical stores (`RunStore`, `WorkspaceStore`, `DurableRunStore` canonical,
  core `AuditLog`, durable effect context) — never `stores.*` dicts or `dag_run_store`;
- add the legacy surface it supersedes to the retirement ledger with a delete-by
  milestone (§5), or state that it supersedes none;
- carry `@pytest.mark.ac` markers for the P0 criteria it relies on, so
  `check-ac-state --mandate` measures them (an unproven marker with a reason is allowed;
  silence is not).

Sequencing inside Phase 1 (each row blocks the next):

| Step | Builds | Retires (ledger entry) | Needs |
|---|---|---|---|
| 1 | Workspace Home shell + generated client + Principal-aware nav (#1048 first slice) | `Dashboard.tsx`, `AppShell` static nav, `dashboard_layouts` JsonStore | P0.1–P0.3 |
| 2 | Goal/Run inspection projections (#65, #1036) | `DagRuns.tsx`, `dag_runs` JsonStore, `services/dag_run_store.py` | step 1, #53 |
| 3 | Workspace Agent chat as the front door (#1037, #53) | `Chat.tsx` raw `/v1/chat/stream` path, `chat_sessions` scoping shim | P0.4, A |
| 4 | Backlog / work items (#82, #98–#103) | `WorkItems.tsx`, `Missions.tsx`, `missions`/`mission_steps`/`work_item_drafts` | step 2 |
| 5 | Attention + Waiting (#1049), settings via canonical service (#1050) | `Settings.tsx` elevation body, `user_provider_config`, `Profile.tsx` | P0.5 |
| 6 | Memory / user model (#776, #1047) | `Memory.tsx`, `KnowledgeBase.tsx`, `memory_entries`/`memory_namespaces` dicts, `routes/memory.py` global handlers | #364 |
| 7 | Proactive curation (#1051) | — | steps 5–6 |

## Phase 2 — retire

When a ledger row's replacement is proven (its AC reachable), delete the row's files in the
same PR that flips the AC. The ledger check fails if a listed module is still present after
its delete-by milestone, or if any file outside the ledger imports it.

Exit for the cutover as a whole: the retirement ledger is empty, `stores.py` holds no
`JsonStore`, `_PROTECTED_OPS` has no exemptions without expiry, the raw-fetch and
hand-typed ledgers are empty, and `KNOWN-GAPS.md` no longer lists Conductor in-memory state.

## 5. Retirement ledger (initial content for `quality/workspace-retirement.json`)

Dispositions: **PROJECT** — becomes a Workspace projection over canonical state, page
rewritten on the generated client; **RETIRE** — deleted, no replacement; **MERGE** — folded
into another surface; **KEEP** — outside the Workspace (installer, auth).

### Pages (`packages/hive-conductor/frontend/src/pages`)

| Page | Disposition | Replaced by | Delete-by |
|---|---|---|---|
| Dashboard.tsx (1,329 lines, 15 raw fetch) | PROJECT | Workspace Home #1048 | M3-E |
| DagRuns.tsx, DagBuilder.tsx | PROJECT | Goal/Run inspection #65/#1036, Graph editing over canonical Graph | M3 |
| Missions.tsx, WorkItems.tsx | MERGE | Workspace backlog #82 | M3-C |
| Chat.tsx | PROJECT | Workspace Agent chat #1037 | M3-D |
| Memory.tsx, KnowledgeBase.tsx | PROJECT | user model / Workspace memory #776/#1047 | M3-E |
| Agents.tsx, Topology.tsx, Skills.tsx, MCP.tsx | PROJECT | one "capabilities" projection over the capability registry (#59 supply chain) | M3 |
| Schedules.tsx | PROJECT | canonical `ScheduleStore` (#92) | M3-B |
| Settings.tsx, Profile.tsx | PROJECT | settings service #1050 | M3-E |
| AuditLog.tsx | PROJECT | core audit store (P0.4) | M3 |
| Credentials.tsx | PROJECT | credential router scope (#58 consumers) | M3 |
| Quotas.tsx | PROJECT | Invocation usage (#718 says the ledger is empty today) | M3 |
| MessageBoard.tsx, OptimizationInbox.tsx | MERGE | Attention/Waiting #1049 | M3-E |
| Evolution.tsx, RSI.tsx | PROJECT | Run inspection over canonical Evolve/RSI Runs (#51/#50) | M4/M5 |
| Containers.tsx, CLI.tsx | RETIRE unless #382/#292 give them a contract | — | M4 |
| DesignStudio.tsx, DeckBuilder.tsx | KEEP (own lane #286/#773) | — | — |
| Docs.tsx | RETIRE | — | M3 |
| Login.tsx, Setup.tsx | KEEP (auth/installer) | — | — |

### Routers (`backend/main.py:283-332`)

PROJECT onto canonical services and re-register under the declared permission table:
`/v1/tasks`, `/v1/work-items`, `/v1/program`, `/v1/dag-runs`, `/v1/dag-metrics`,
`/v1/memory`, `/v1/messages`, `/v1/quotas`, `/v1/widgets`, `dashboard_layout`,
`/v1/topology`, `/v1/eval-judge`, `/v1/confirms`, `/v1/cli`, `/v1/setup-checklist`.
KEEP with scoped entries: `/v1/auth`, `/v1/setup`, `/v1/install`, `/v1/hitl` (scoping via
#1058/#1110), `/v1/workspaces`, `/v1/dags`, `/v1/schedules`, `/v1/credentials`,
`/v1/capabilities`, `/v1/providers`, `/v1/harness`, `/v1/ws`, `/v1/profile`, `/v1/audit`
(reads P0.4 store), `/v1/design`.

### In-memory stores (`backend/stores.py`, 15 `JsonStore` + dicts)

`missions`, `mission_steps`, `schedules`, `skills`, `agents`, `mcp_servers`, `mcp_tools`,
`containers`, `memory_entries`, `memory_namespaces`, `workspaces`, `persona_feedback`,
`chat_sessions`, `cli_sessions`, `users`, `sessions`, `program_contexts`,
`work_item_drafts`, `dags`, `messages`, `audit_log`, `eval_verdicts`, `optimizer_proposals`,
`user_provider_config`, `dashboard_layouts`, `oauth_identity_links`, `dag_runs`,
`registration_invitations`.

Every one is a `RETIRE` row: the replacement is the canonical store named in
CONVERGENCE-MATRIX.md for that concept, or a Workspace-scoped durable store added under
#364. `users`, `sessions`, `oauth_identity_links`, `registration_invitations` retire into
the P0.1 identity store. `audit_log` retires under P0.4. `dag_runs` and
`services/dag_run_store.py` retire under step 2.

## 6. Guards that keep the plan honest

**Epic closure by evidence, not keyword.** `scripts/check-closure-targets.py`: parse the
PR body for `Closes/Fixes/Resolves #N`; fail if the target's title starts with `[EPIC]`,
`[MILESTONE]`, `[INITIATIVE]`, or the target has sub-issues. Epics close by hand when
`check-ac-state` reports every criterion `reachable`. This is the #56 hole.

**Freeze extended to surfaces.** Add to `quality/m1-convergence-freeze.json` (or an M3
sibling) a rule: a new file under `frontend/src/pages` that declares a backend entity type
or calls `fetch` outside `src/lib` is a new UI authority and fails the freeze check.

**Fallback construction is a second authority.** A fitness test (generalizing #1082) that
`EngineService`, `dag_agents` and the node resolver never construct
`InMemoryOutcomeStore`, `default_capability_registry()` or `InMemoryDurableRunStore` when a
Container exists — they receive the Container's instance or fail to start.

**No silent downgrade.** A `postgresql://` configuration that yields any in-memory store
fails startup (#122 fixed this for the memory stores; P0.5 extends it to the effect ledger;
#333 covers Conductor state).

## 7. Prerequisite issues to open (right-hand column)

1. **Durable Binding/Invocation/Approval stores and backend-selected effect context** — A.
   Owner: capability seam (#15). PostgreSQL implementations + Alembic migration; container
   selection; process-default identity. Blocks P0.5 and #804.
2. **Flat-layout module collisions** — B. Decide the package name for the Conductor backend;
   until then P0.6 forbids growth.
3. **One persistence mechanism for Conductor** — F. PostgREST HTTP layer vs core asyncpg
   stores; SQLite/Alembic parity check (a script that diffs `CREATE TABLE` columns against
   the Alembic head); `DurableRunStore` conformance suite; `list_due` on the legacy twins.
4. **Lifecycle checker: `Literal` status types** — H. `services.rsi.RunStatus` evades
   `check-execution-lifecycles.py:30`.
5. **Warden at the remaining inbound boundaries** — A2A inbound, RSI harvest, Turing backend.
   Children of #66 with the three paths named.
6. **Turing backend public-route list under the public-routes gate** — D. Bind
   `check-public-routes.py` to `maistro-turing/backend/middleware/auth.py` as well.

## 8. Order of operations, one line

Open §7 issues → land P0 checks red with baselines → P0.1–P0.4 green → A green → P0.5
green → Phase 1 steps 1–7, each PR retiring its ledger row → Phase 2 deletes → epics close
by ac-state, never by keyword.
