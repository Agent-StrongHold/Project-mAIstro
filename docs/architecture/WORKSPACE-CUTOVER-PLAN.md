# Workspace Cutover Plan

**Status:** active cutover plan — v1.0 amendments ratified 2026-10-01 (see §9); release contract in [ROADMAP.md](../../ROADMAP.md)
**Owners:** #1046 (Adaptive Workspace), #804 (Persistent Workspace Agent), #53 (Conductor onto Conduit + canonical Runs), #65 (Workspace-centric inspection), #82 (Workspace backlog)
**Companion policy:** [M1-CONVERGENCE-FREEZE.md](M1-CONVERGENCE-FREEZE.md) · [CONVERGENCE-MATRIX.md](CONVERGENCE-MATRIX.md) · [KNOWN-GAPS.md](../../KNOWN-GAPS.md) · [BACKLOG.md](../../BACKLOG.md) `[conductor-402]`–`[conductor-413]`

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

The per-feature Workspace-UI/API/CLI entry-point inventory that this plan's "parity"
evidence plugs into is [FEATURE-PARITY-MATRIX.md](FEATURE-PARITY-MATRIX.md) (#1874); it
also records the approved v1.2 Evolution staging (§9) as a preserved decision.

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

**Landing a check that starts with debt takes two merges.** Under
[RATCHET-PROVENANCE.md](../ci/RATCHET-PROVENANCE.md) a checker reads its tolerated set and
its grants in `quality/ratchet-authorizations.json` from the trusted merge base, never
from the change under review. A ledger that does not exist at the base tolerates nothing,
so a check cannot introduce its own baseline. The first PR grants each starting entry under
the ratchet's name; the second, stackable on it, adds the checker and a ledger matching
those grants. Each checker gets a row in RATCHET-PROVENANCE.md's inventory in the same
PR. Once the second PR banks the ledger, **delete those starting-debt grants from the
candidate tree in the same PR.** Permission is read from the trusted base, so the deletion
does not remove the authorization for banking; leaving the grants in place would let a later
change re-bank the same debt without a new review ([`SPEC-082926-6f49`](../specs/SPEC-082926-6f49-authorized-floor-fall-for-a-corrected-measurement.md)
spent-grant bookkeeping; cutover S1.0 lands the grants in
[#1804](https://github.com/Agent-StrongHold/Project-mAIstro/pull/1804)).

**Acceptance criteria are registered in SPEC-100126-c041**
(`docs/specs/SPEC-100126-c041-workspace-cutover-phase-0-contract.md`, PR [#1768](https://github.com/Agent-StrongHold/Project-mAIstro/pull/1768)). The
acceptance-state checker accepts numeric IDs only, so plan label AC-P*n* is
`SPEC-100126-c041/AC-n`: a test proving AC-P1 carries
`@pytest.mark.ac("SPEC-100126-c041/AC-1")`, and the PR that proves it deletes that
criterion's `ac-state: unproven` comment from the spec. P0.6 had no AC line here; the
spec derives AC-6 from P0.6's invariant and check.

### P0.1 One principal

**Invariant.** Exactly one principal type crosses a service boundary. It lives in
maistro-core, carries `user_id`, `roles`, `scopes`, Workspace memberships and the ADR-068
scope axes, and every HTTP service constructs it at its auth boundary.

**Today.** `maistro_server.api.principal.AuthenticatedPrincipal` (roles only),
hive `HiveUser` → `request.state.user` dict (`middleware/auth.py:296`), Turing
`dict` **or** `ServiceIdentity`, canvas `CurrentUser`, core `AuthContext`, core `UserInfo`.
maistro-server bridges by hand at `api/chat_completions.py:187`.

**Check.** `scripts/check-principal-identity.py`, run in `quality.yml`, with
`packages/maistro-core/tests/fitness/test_principal_identity.py` asserting the ledger
matches the tree. An AST scan of `packages/*/src` and the hive and Turing backends records
two kinds of entry: each file that touches `<x>.state.user`, directly or through
`getattr`/`setattr`/`hasattr`, and each class named `*Principal`/`*User`/`*Identity` with
a `role`/`roles` field outside the listed owner modules. Baseline ledger
`quality/principal-identity-baseline.json`, ratchet to zero.

**Measured starting debt (2026-10-01): 32 entries.** Four parallel principal classes —
maistro-server `AuthenticatedPrincipal` (`api/principal.py`), hive `HiveUser`
(`models/schemas.py`), canvas `CurrentUser` (`auth.py`) and core `_SubsystemIdentity`
(`privilege.py`) — and 28 files reading dict-shaped `state.user`:
23 hive routes, 2 hive services, hive and Turing auth middleware, and Turing
`security.py`. Most hive reads go through `getattr(request.state, "user", ...)`, which an
attribute-only scan misses (a first draft of the check counted 3).

**AC text (for #53).** "AC-P1: every authenticated request in maistro-server, hive-conductor
and the Turing backend yields one `maistro.identity.Principal`; no handler reads a
dict-shaped user; the fitness ledger is empty."

### P0.2 One permission vocabulary, default-deny route table

**Invariant.** Every registered router prefix has either a declared permission or a declared,
reviewed reason it has none. Unmatched is denied, not allowed. One vocabulary
(`scope.verb`) is shared by the middleware, `Principal.scopes`, and Binding `policy_refs`.

**Today.** `middleware/auth.py:411-464` returns `None` for unmatched prefixes and
`dispatch` forwards; 18 routers (`/v1/tasks`, `/v1/memory`, `/v1/quotas`, `/v1/work-items`,
`/v1/program`, `/v1/dag-runs`, …) have no entry; the `endswith("/invoke")`
suffix exemption was removed by #403 — elevation binds to registered
capability identifiers, not URL naming, and any future route with that
suffix needs an explicit reviewed policy like every other route — leaving
`endswith("/feedback")` as the only suffix exemption.
`PrivilegeMiddleware` is a no-op.

**Check.** `scripts/check-route-permissions.py`, a sibling of `check-public-routes.py`
rather than an extension of it: it imports the hive app to read the mounted `/v1/{segment}`
prefixes, so it runs in `quality.yml` beside `check_enumerations.py`, not in the
bare-`python3` lint job. Before judging prefixes it reads `app.state.optional_routers` and
refuses when any optional router (`routes.design`, `routes.canvas`, `routes.evolution`,
`routes.rsi`) failed to import — the same completeness rule as
`scripts/check-frontend-api-routes.py`, so a missing package cannot produce a partial census
that pre-approves or omits production routes. Registry `quality/route-permissions.json`: every mounted prefix
not public by `quality/public-routes.json` must appear with exactly one of a permission or
an `exempt_reason`, plus owner, disposition and reason; a temporary entry also needs an
issue and an unexpired date — the shape `public-routes.json` already uses. A registry entry
for a prefix nobody mounts fails, because it would pre-approve a future route. Suffix
exemptions are listed as exact paths, not suffixes. Undeclared prefixes are ledgered in
`quality/route-permissions-baseline.json`; ratchet to zero, and to zero exemptions
without an expiry.

**Measured starting debt (2026-10-01): 40 prefixes**, not the 18 counted by hand — every
authenticated `/v1` prefix the hive app mounts, since the registry starts empty.

**AC text (for #53 / #373).** "AC-P2: `check-route-permissions.py` proves every registered
Conductor route is either scoped, public-by-declaration (via
`quality/public-routes.json`), or exempt-by-declaration (via
`quality/route-permissions.json`); an undeclared route fails CI;
`PrivilegeMiddleware` is deleted or enforces its table."

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

**Today (2026-10-02, after #1321/#1760).** Backend selection exists:
`container._wire_capability_effects` builds `new_sqlite_effect_context` with a SQLite pool,
`new_postgres_effect_context` with a PostgreSQL pool, and the in-memory context otherwise,
then registers boot Bindings on whichever store it chose. Two halves of the invariant are
still open. `CapabilityEffectContext` carries no Approval store, so an approval is not
durable on any backend. And `effect_context.default_effect_context()` is still its own
`lru_cache`d in-memory context — the fallback registry-constructed effect nodes use — not
the Container's instance.

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

### P0.7 Crash-window invariants on the execution spine

**Invariant.** No Run can remain RUNNING with no Attempt owning it and no sweep that will
re-derive its state. Every two-write sequence on the spine (NodeRun terminal → Run
settlement; frontier NodeRun creation → continuation checkpoint; Attempt completion write;
terminal continuation → canonical mirror) either commits atomically or is repaired by a sweep.

**Today.** Four windows leave a Run RUNNING and invisible to both recovery paths
(`recovery.py` selects QUEUED or due-by-`resume_at` only): `runs/reconciliation.py:206-207`
(last NodeRun commits, process dies before `_settle_run_if_fully_observed`, nothing calls it
again); `attempt_executor.py:414-419` (`_ensure_frontier_node_runs` outside the try, prior
checkpoint already cleared `resume_at`); `runs/execution.py:430` (a successful Attempt's
terminal write outside the try → whole-Run `PhysicalExecutionError`, result discarded, retry
budget skipped); `canonical_store.py:126-131` (`_reconcile_run` repairs WAITING/PAUSED only,
not a terminal continuation). The 2026-09-08 core-foundation review, §2.1 and §3.1–3.4.

**Check.** One sweep that lists RUNNING Runs and re-derives terminal state from NodeRuns and
continuations, wired on the same cadence as `dag_recovery.py`; a crash-injection test per
window using the forced-interleaving pattern already in
`tests/workspaces/test_workspace_store_conformance.py:369-432`.

**AC text (for #804 / #62).** "AC-P7: a process killed at any of the four named points leaves a
Run that the next recovery tick settles or resumes; no Run is RUNNING with no live Attempt
after one tick."

### P0.8 Store-boundary scope, named

**Invariant.** #364's principle ("scope enforced at the durable store boundary") has an
explicit child for every store the Workspace consumes.

**Today.** Untracked leaves: no `WorkspaceStore`/`ProjectScopeStore` method takes a principal
and `EffectiveAuthorization` is consulted by one function; `Run.actor_principal_id` is an
unvalidated optional string that becomes accounting `user_id` (`runs/model.py:272`,
`consumption.py:301`); `get_run/get_node_run/get_attempt` are unscoped primary-key lookups;
`AuditLog.get_entries(org_id=...)` accepts the argument and ignores it because the column does
not exist (`pg_audit.py:13-18`, migration 005).

**Check.** A conformance test per store that a principal outside the scope cannot read or
mutate by id, run against all three backends.

**AC text (for #364).** "AC-P8: workspaces, projects, runs and audit each have a
store-boundary scope test; `actor_principal_id` is required and validated at admission;
audit rows carry and filter by `org_id`."

### P0.9 The Agent scans what the model sees, not the last raw turn

**Invariant.** Warden receives the normalized, turn-aggregated text the model will receive.

**Today.** `Warden.scan(content, boundary)` takes one string; the override patterns are
whole-word and are defeated by letter spacing and leetspeak (reproduced); the PII redactor
misses Slack tokens, bare AWS secret keys and `my_secret = '…'` (reproduced); a payload split
across two user turns scans clean on each. Sentinel defaults to allow for a tool absent from
the permission table (ADR-072726-0d6b, proposed fail-closed not built).

**Check.** A boundary test in the Workspace Agent's chat path asserting the scanned string is
the aggregated context; the spaced/leet/split cases added to the Warden suite as expected
detections; `permission_table` non-empty asserted at Workspace deploy.

**AC text (for #1037 / #66).** "AC-P9: the Workspace Agent's inbound scan covers the
aggregated turn context after normalization; the three reproduced evasions are detected; the
Sentinel permission table is armed in every supported profile."

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
| 2 | Goal/Run inspection projections (#65, #1036) | `DagRuns.tsx`, `dag_runs` JsonStore, `services/dag_run_store.py` | step 1, #53, P0.8 |
| 3 | Workspace Agent chat as the front door (#1037, #53) | `Chat.tsx` raw `/v1/chat/stream` path, `chat_sessions` scoping shim | P0.4, P0.7, P0.9, A |
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
`/v1/topology`, `/v1/eval-judge`, `/v1/cli`, `/v1/setup-checklist`.
RETIRED: `/v1/confirms` (#48) — unreachable process-local HA confirmation store; human
approval is a waiting human NodeRun answered through `/v1/hitl`. It has no router module
left, so it has no ledger row. `/v1/dag-metrics` is served by `routes/metrics.py`.
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
PR body for `Closes/Fixes/Resolves #N`; fail if the target's leading bracketed tag contains
the word EPIC, MILESTONE or INITIATIVE, or the target has sub-issues. The tag test, not a
literal `[EPIC]` prefix, because real titles qualify the tag: `[EPIC M1-B]`,
`[MILESTONE M4]`, `[MASTER INITIATIVE]`. Epics close by hand when `check-ac-state` reports
every criterion `reachable`. This is the #56 hole. The workflow triggers on `opened`,
`reopened`, `synchronize` and `edited`, and the script reads the body from the event
payload, so a body edit re-runs the check against the body as it now stands. Triggering
only on opened/reopened/synchronize is not enough: a `Closes #N` appended after the final
push would ride a green check (vouching for the old body) straight into the merge.

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
green → **M1 RunStore unification (#251)** → Phase 1 steps 1–6 (step 7 deferred v1.1), each PR
retiring its ledger row → Phase 2 deletes → epics close by ac-state, never by keyword.

### Phase 0 progress (2026-10-02)

| Item | State |
|---|---|
| §5 retirement ledger + gate | in review, [#1766](https://github.com/Agent-StrongHold/Project-mAIstro/pull/1766); delete-by values follow the §9 v1.0 amendments |
| §6 epic-closure guard | in review, [#1765](https://github.com/Agent-StrongHold/Project-mAIstro/pull/1765) |
| AC-P1–P9 registration | in review, [#1768](https://github.com/Agent-StrongHold/Project-mAIstro/pull/1768) |
| P0.1, P0.2 grants | in review, [#1804](https://github.com/Agent-StrongHold/Project-mAIstro/pull/1804); 31 and 40 entries, re-measured on `develop` at `8ccab2c9` |
| P0.1, P0.2 checks | in review, [#1805](https://github.com/Agent-StrongHold/Project-mAIstro/pull/1805); red until #1804 is in its merge base |
| P0.3 check | in review; 64 raw fetch + 142 hand-typed declarations banked |
| P0.4, P0.6–P0.9 checks | not started |
| P0.5 | backend selection landed with #1321 (see P0.5 "Today"); durable approvals and one process-wide context remain; the check is not started |

An early draft of the P0.1/P0.2 checks reached `develop` without review on 2026-10-01 and
was reverted by [#1769](https://github.com/Agent-StrongHold/Project-mAIstro/pull/1769); the
checks described in P0.1 and P0.2 above are the corrected design.

### Landed elsewhere that moves this plan

Work merged outside the cutover PRs, and which item it advances. Re-read before starting
the item; none of these closes a cutover criterion on its own.

| PR | What landed | Plan item |
|---|---|---|
| [#1321](https://github.com/Agent-StrongHold/Project-mAIstro/pull/1321) | `new_sqlite_effect_context` / `new_postgres_effect_context` give a configured database durable Binding, Invocation and event authority; SQLite Invocation claim is atomic; `check_direct_effects.py` fails closed on dynamic-URL graph-node HTTP | §7 prerequisite A (durable Binding/Invocation; Approval store not covered) → P0.5 |
| [#1760](https://github.com/Agent-StrongHold/Project-mAIstro/pull/1760) | boot Bindings register on durable stores, so persistence no longer disables `self_repair` and `/v1/harness` | §7 A; #1133 (closes #1759) |
| [#1795](https://github.com/Agent-StrongHold/Project-mAIstro/pull/1795) | dead PostgreSQL-event warning removed | #1133 AC-15 |
| [#1617](https://github.com/Agent-StrongHold/Project-mAIstro/pull/1617) | ADR-082326-c126 accepted: one Run per chat turn, admitter-bounded retention, a turn without a Run is refused (closes #131) | Phase 1 step 3; P0.7 |
| [#1618](https://github.com/Agent-StrongHold/Project-mAIstro/pull/1618) | adversarial kill-recovery evidence pack (closed #62 on 2026-09-27) | P0.7: build the crash-window check on this evidence; #804 remains the open owner |
| [#1555](https://github.com/Agent-StrongHold/Project-mAIstro/pull/1555) | stable Workspace Agent identity and per-user default Workspace (closed #1037 on 2026-09-23) | Phase 1 step 3 and AC-P9 cite #1037, which is closed; their open owner is #804 |
| [#1735](https://github.com/Agent-StrongHold/Project-mAIstro/pull/1735) | durable, recoverable task queue (#91) | #251 RunStore unification (the queue is what creates canonical Runs) |
| [#1718](https://github.com/Agent-StrongHold/Project-mAIstro/pull/1718) | EngineService startup atomic and health-visible on partial failure (#1181) | §6 "fallback construction is a second authority" |
| [#1670](https://github.com/Agent-StrongHold/Project-mAIstro/pull/1670) | Canvas API/store/lease path operable and restart-safe (#851) | v1.0 Canvas blocker (§9 issue cross-reference) |

## 9. v1.0 stakeholder amendments (2026-10-01)

Ratified decisions that tighten this plan for the v1.0 tag. Item IDs: [BACKLOG.md](../../BACKLOG.md).

**Verdict:** directionally aligned; v1.0 is **stricter** — delete legacy pages (not PROJECT-to-M3), unify run store before step 2, Canvas/Design Studio are blockers, Evolution hidden until v1.2.

### Critical path

```text
Phase 0 (contract)  →  M1 RunStore (#251)  →  Phase 1 steps 1–6  →  M2 security on Workspace Agent (#1037)  →  v1.0 tag
```

M2 security (#66) runs **after** Workspace Agent exists — not on legacy `Chat.tsx`.

### Phase 1 step mapping (v1.0 blockers)

| Step | Issue | v1.0? |
|------|-------|-------|
| 1 Workspace Home | #1048 | Yes |
| 2 Goal/Run inspection | #65, #1036 | Yes — requires RunStore unification first |
| 3 Workspace Agent chat | #1037 | Yes |
| 4 Backlog / work items | #82 | Yes |
| 5 Attention + settings | #1049, #1050 | Yes (Attention); settings partial OK |
| 6 Memory / user model | #776, #1047 | Yes — workspace + user + global; team deferred v1.1 |
| 7 Proactive curation | #1051 | **Deferred v1.1** |

### Explicit v1.0 wiring

| Module | v1.0 |
|--------|------|
| `tool_binding.py` dispatch | Yes |
| `repo_scanner`, `pipeline_orchestrator`, `chatbot_integration` | Yes |
| repertoire → Capabilities (#59) | Yes |
| builders → Backlog (#49) | Yes |
| delivery gateway (#57) | Yes |

### Retirement ledger amendments

| Page | Prior disposition | v1.0 amendment |
|------|-------------------|----------------|
| Dashboard.tsx | PROJECT, delete M3-E | **DELETE v1.0** (Home replaces) |
| Chat.tsx | PROJECT, delete M3-D | **DELETE v1.0** |
| Agents/Skills/MCP/Topology | PROJECT, delete M3 | **DELETE v1.0** (Capabilities) |
| Memory/KnowledgeBase | PROJECT, delete M3-E | **DELETE v1.0** |
| Missions/WorkItems | MERGE backlog M3-C | **DELETE v1.0** (Backlog) |
| Evolution.tsx | PROJECT M4/M5 | **DELETE/HIDE v1.0** (restore v1.2) |
| CLI.tsx | RETIRE unless contract | **PROJECT v1.0** (#292 implement) |
| Containers.tsx | RETIRE unless contract | **PROJECT v1.0** (#382 implement) |
| DesignStudio.tsx | KEEP | **PROJECT v1.0** (blocker scope) |
| Login/Setup | KEEP | KEEP |

### Run store

Step 2 AC requires a **single run browser** — no new callers of `DurableRunStore` / `dag_run_store`. Aligns with #251 and P0.7 crash-window work.

### Memory scopes

Workspace + user + **global** for v1.0. Team axis returns `NotImplemented` or hidden in UI until v1.1.

### Issue cross-reference

| Workstream | Issues |
|------------|--------|
| Cutover epic | #1046, #804, #53, #65, #82 |
| Phase 0 | #53, #373, #325, #364, #1082 |
| Workspace UI | #1048, #1037, #1049, #776 |
| Run unification | #251, #736, #1036 |
| Canvas | #735, #851, #93 |
| Capabilities | #59, #848 |
| Security on Agent | #66, #1171, #1202 |
