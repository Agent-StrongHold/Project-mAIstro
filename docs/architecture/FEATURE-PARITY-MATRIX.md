# Workspace / API / CLI feature parity matrix

**Status:** living inventory — owned by [#1874](https://github.com/Agent-StrongHold/Project-mAIstro/issues/1874) (parent initiative [#449](https://github.com/Agent-StrongHold/Project-mAIstro/issues/449)).
**Evidence commit:** `afb8659ac4829ad8d674fdd7e92ad24e2a4dc2a9` (branch base `a25e2f5ce23eed589c938a08104cf120c2f3093c` + M8 research commits; all `path:line` citations below are at this commit).
**Scope:** one source-grounded inventory of the product's supported features and their Workspace UI, API, and CLI entry points. This is a traceability document, not an implementation plan and not a compatibility contract. It creates no authority, no feature backend, and no compatibility layer.

## Method — what counts as evidence

Per #1874: completeness is **not** inferred from package names or DTOs. Every cell below is grounded in one of four observable artifacts, each re-derivable at the evidence commit:

1. **CLI: executed registration.** `uv run maistro --help` and each subcommand's `--help` (Typer prints only commands actually registered via `app.add_typer` — [`packages/maistro-core/src/maistro/cli/__init__.py:42-52`](../../packages/maistro-core/src/maistro/cli/__init__.py)). Standalone console scripts come from `[project.scripts]` tables (`maistro-registry`, `maistro-rsi`, `maistro-rsi-autorun`, `maistro-install`).
2. **API: effective route table.** Both FastAPI apps were imported in-process and iterated with the repo's sanctioned iterator `iter_effective_routes` ([`packages/maistro-server/src/maistro_server/api/route_table.py`](../../packages/maistro-server/src/maistro_server/api/route_table.py)) — naive `app.routes` reads are false witnesses under fastapi ≥ 0.141 lazy inclusion. Result: **109** unique method+path operations for `maistro-server`, **269** for the Workspaces BFF (`packages/hive-conductor/backend`) in a dev venv without the `maistro-design` extra (that optional router degrades explicitly — see Gating below; +10 design routes when installed). Registrations: [`packages/maistro-server/src/maistro_server/main.py:674-701`](../../packages/maistro-server/src/maistro_server/main.py), [`packages/hive-conductor/backend/main.py:360-417`](../../packages/hive-conductor/backend/main.py).
3. **UI: registered routes and real controls.** React Router registrations ([`packages/hive-conductor/frontend/src/App.tsx:174-223`](../../packages/hive-conductor/frontend/src/App.tsx)), nav entries ([`packages/hive-conductor/frontend/src/components/AppShell.tsx:30-56`](../../packages/hive-conductor/frontend/src/components/AppShell.tsx)), and mutating `fetch` calls from the machine-checked `quality/shipped-surface-truth.json` (220 backend / 68 frontend surfaces at this commit). A page that renders but calls no backend for a capability is inventoried as absent, not inferred.
4. **Cross-checks.** `scripts/check-shipped-surface-truth.py` and `scripts/check-convergence-matrix.py` hold neighboring inventories honest; this document adds no claims that contradict them.

Re-derivation (from a synced workspace):

```bash
uv run maistro --help   # and each subcommand
uv run --package maistro-server python - <<'EOF'
from maistro_server.main import app
from maistro_server.api.route_table import iter_effective_routes
for r in iter_effective_routes(app.routes):
    if getattr(r, "path", None) and getattr(r, "methods", None):
        print(sorted(r.methods), r.path)
EOF
# same for packages/hive-conductor/backend with sys.path including backend/
```

## State vocabulary

| State | Meaning |
|---|---|
| **supported** | Registered/routable today on that surface; executes through the canonical authority. |
| **gated** | Ships, but only behind an install extra, separate package, or explicitly-degraded startup. |
| **staged** | Registered and observable but deliberately held from the release surface (hidden nav, placeholder) with an approved restore scope. |
| **missing** | No counterpart on that surface at the evidence commit. |
| **unknown** | Source cannot settle availability; an unresolved disposition or unverified owner is recorded. |

## The matrix

Cell marker is the surface's state from the vocabulary above. "—" means the surface has no meaningful entry point for the row and none is claimed.

### A. Admission and identity

| Feature | Canonical authority | Workspace UI | API | CLI |
|---|---|---|---|---|
| Account register / login / logout / whoami | `maistro.auth`, `maistro.identity` (service-key + session store) | supported — `Login.tsx`, `Setup.tsx`, `AccountBanner.tsx` POST `/v1/auth/*` | supported — `/v1/auth/register`, `/login`, `/logout`, `/whoami`, `/users`, `/registration` | missing (CLI consumes `MAISTRO_API_TOKEN` env; no account commands) |
| Privilege elevation (authorized raise) | `maistro.privilege` / `maistro.policy` (convergence-matrix authorization owners) | supported — `Settings.tsx` POST `/v1/auth/elevate` | supported — `POST /v1/auth/elevate` | missing |
| Request admission (work starts) | Conduit/container front door → canonical 202 receipt (`maistro.tasks`, ADR-018) | supported — Chat/Dashboard POST `/v1/chat/stream`, `/v1/chat/complete` | supported — BFF `/v1/chat/*`, `/v1/tasks`; server `POST /v1/tasks` | missing (no remote submit; `maistro builders` is a local TUI session) |
| Authorization / refusal on every path | Warden/Sentinel + per-route middleware; workspace membership checks | supported — `/v1/*` gated by AuthMiddleware; SPA fallback deliberately unauthenticated (non-`/v1/` only) | supported — same middleware; non-disclosing detail responses per #1036 | supported — same server-side refusals; CLI is an httpx client (`MAISTRO_API_URL`) |

Evidence: [`routes/auth.py`](../../packages/hive-conductor/backend/routes/auth.py) registrations in [`backend/main.py:361`](../../packages/hive-conductor/backend/main.py); SPA fallback comment [`backend/main.py:427-436`](../../packages/hive-conductor/backend/main.py); CLI client [`cli/_approvals.py:23-25`](../../packages/maistro-core/src/maistro/cli/_approvals.py); admission backpressure landed at base `a25e2f5ce` (#1182).

### B. Agent and tool selection

| Feature | Canonical authority | Workspace UI | API | CLI |
|---|---|---|---|---|
| Agent registry / CRUD / forge / scan | `maistro.agents` + `maistro.agents.intents` routing | supported — `Agents.tsx` (`/agents`) | supported — `/v1/agents`, `/v1/agents/forge`, `/v1/agents/scan`, `/v1/agents/{id}` | missing |
| Model providers + activation + keys | `maistro.providers`, `maistro.router` (pure selection policy) | supported — `LlmProviders.tsx` POST activate / PUT key | supported — `/v1/providers`, `/v1/providers/{name}/activate`, `/v1/providers/{name}/key` | missing |
| Credentials + master-key rotation | `maistro.credentials` (encrypted per-user store) | supported — `Credentials.tsx` (`/credentials`) | supported — `/v1/credentials/*` | supported — `maistro security rotate-credential-key` (operator path) |
| Skills + Forge + scan + toggle | `maistro.skills`, `maistro.code_registry` (signing + trust tiers, #59 path) | supported — `Skills.tsx` (`/skills`) | supported — `/v1/skills`, `/forge`, `/scan`, `/{id}`, `/toggle` | missing |
| MCP integrations (discovery / trust) | `maistro.integrations` + Warden/policy (#59 supply-chain path) | supported — `MCP.tsx` (`/mcp`, nav "Integrations") | supported — `/v1/mcp/servers*`, `/discover`, `/test`; `unknown` on `/discover` and `/{id}/scan` (unresolved surface-truth dispositions) | missing |
| Capability slots + approvals inbox | `maistro.capabilities` (`governed_invocation`, `approval_store`) | missing — no UI calls `/v1/capabilities/*` or `/v1/hitl/*` (G6) | supported — `/v1/capabilities*`, `/v1/hitl/{run}/{node}/answer|cancel`, `/v1/hitl/pending` | supported — `maistro approvals list|approve|deny` |

Evidence: BFF registrations [`backend/main.py:370,376,382`](../../packages/hive-conductor/backend/main.py); approvals CLI registration [`cli/__init__.py:46`](../../packages/maistro-core/src/maistro/cli/__init__.py); absence of `/v1/capabilities` and `/v1/hitl` callers verified by repo-wide frontend grep at the evidence commit.

### C. Work admission and execution

| Feature | Canonical authority | Workspace UI | API | CLI |
|---|---|---|---|---|
| Chat turns (stream / complete) | Canonical Graph/Run spine via shared Conductor chat | supported — `Chat.tsx`, `Dashboard.tsx` | supported — `/v1/chat/stream`, `/complete`, sessions CRUD | missing |
| Graph (DAG) authoring | `maistro.graph`; definitions are plans, not Runs | supported — `DagBuilder.tsx` (`/dags`) | supported — `/v1/dags` CRUD + nodes/edges + activate | missing |
| Run execution (start work) | `Graph → Run → NodeRun → Attempt` (one execution identity) | supported — author + run from `DagBuilder.tsx` | supported — `POST /v1/dags/{id}/run` ([:359](../../packages/hive-conductor/backend/routes/dags.py)), `/v1/dags/run-champion` ([:417](../../packages/hive-conductor/backend/routes/dags.py)), `/v1/schedules/{id}/run` | partial — `maistro fixtures seed` executes fixture Runs through the canonical spine; no general start command |
| Mission / task queue (Conductor) | `maistro.tasks` admission + Conductor missions | supported — `Missions.tsx` (`/missions`) | supported — BFF `/v1/tasks*`; server `/v1/tasks` 202-receipt surface | missing |
| Schedules (recurrence → Run) | `maistro.scheduling` (evaluate decides; Run owns execution) | supported — `Schedules.tsx` (`/schedules`) | supported — `/v1/schedules` CRUD + history + run | missing |
| Builders (spec→tests→code→review) | `maistro.builders` on the canonical spine — convergence owned by #49 | missing — no Builders page (G1) | missing — no Builders routes in either app (G1) | supported — `maistro builders` interactive TUI (gated: needs `textual` extra; [`cli/_builders.py:16-33`](../../packages/maistro-core/src/maistro/cli/_builders.py)) |
| Evolve cycles / tournaments | `maistro_evolve` on the canonical spine — owned by #51 | staged — `/evolution` route registered ([App.tsx:218](../../packages/hive-conductor/frontend/src/App.tsx)), **no nav entry** ([AppShell.tsx:30-56](../../packages/hive-conductor/frontend/src/components/AppShell.tsx)); restore scope v1.2 (G2) | gated — `/v1/evolution/*` via optional router with explicit degradation ([backend/main.py:416](../../packages/hive-conductor/backend/main.py)) | missing (no product CLI; `maistro-evolve` is a library) |
| RSI cycles | `maistro_rsi` as downstream work-source consumer — owned by #50 | supported surface, gated release — `/rsi` in nav ([AppShell.tsx:52](../../packages/hive-conductor/frontend/src/components/AppShell.tsx)); one unresolved surface-truth row on `RSI.tsx` (unknown, G3) | gated — `/v1/rsi/*` via optional router ([backend/main.py:417](../../packages/hive-conductor/backend/main.py)) | gated — separate package scripts `maistro-rsi`, `maistro-rsi-autorun` (not root workspace deps, [pyproject.toml:381-382](../../pyproject.toml)) |

### D. Inspection and control

| Feature | Canonical authority | Workspace UI | API | CLI |
|---|---|---|---|---|
| Run list / detail by canonical ID | `maistro.runs` + canonical store (one Run truth, #1036) | partial — `DagRuns.tsx` is a read-only SSE viewer ([DagRuns.tsx:1-11](../../packages/hive-conductor/frontend/src/pages/DagRuns.tsx)); no cancel/control control (G5) | supported — BFF `GET /v1/dag-runs`, `/{run_id}`, `/{run_id}/events`; server `GET /v1/runs/{run_id}`, `/node-runs` | missing (G5) |
| Run cancel / control | #1169 canonical cancellation; #1036 control seam | missing — no UI control calls any cancel route (G5) | supported — BFF `POST /v1/dag-runs/{run_id}/cancel` ([:82](../../packages/hive-conductor/backend/routes/dag_runs.py)); server `POST /v1/runs/{run_id}/cancel` ([runs.py:89](../../packages/maistro-server/src/maistro_server/api/runs.py)) | missing (G5) |
| Run retry | #1169 / #1036 control plane — **no owner confirmed** | missing | missing | missing (P-2) |
| Node-level inspection / feedback | NodeRun/Attempt projections | supported — node click-through in `DagRuns.tsx` | supported — `/v1/dag-runs/{run_id}/events`, `/v1/dag-runs/{run_id}/feedback`, node feedback | missing |
| Container / sandbox lifecycle | `maistro.sandbox` + Conductor container service | supported — `Containers.tsx` (`/containers`) | supported — `/v1/containers*` incl. build/start/stop/restart/logs; `unknown` on `/build` (unresolved surface-truth disposition) | supported — `maistro sandbox status` (host isolation report) |
| HITL answers inside a live Run | `maistro.capabilities` approvals + HITL routes | missing — no UI caller (G6) | supported — `/v1/hitl/pending`, `/{run}/{node}`, `/answer`, `/cancel`, `/expire` | supported — `maistro approvals list|approve|deny` |

### E. Durable state

| Feature | Canonical authority | Workspace UI | API | CLI |
|---|---|---|---|---|
| Durable Run records | `runs.pg_store` (canonical), document-shaped graph stores | supported — read via DagRuns | supported — read/control routes above | supported — `maistro archive list|show` for pre-convergence durable runs (explicitly scoped read path) |
| Memory / knowledge entries | `maistro.memory` (scope/exposure authorization) | supported — `KnowledgeBase.tsx`, `Memory.tsx` POST/PATCH/DELETE `/v1/memory/entries*` | supported — `/v1/memory/*`; `unknown` on `/entries/{id}/contradict` (unresolved surface-truth disposition) | missing |
| Workspace work-source (BacklogItem) | `maistro.workspaces` stores + `projects.authorization` (#82/#50 contract) | supported — `Backlog.tsx` (`/backlog`), `WorkItems.tsx` (`/work-items`) | supported — BFF `/v1/backlog*`, `/v1/work-items*`; server `/v1/workspaces/{id}/backlog/{item}/history` | missing |
| Conversation / schedule history durability | `maistro.sessions` + per-domain stores | supported — session lists in Chat / Schedules | supported — `/v1/chat/sessions*`, `/v1/schedules/history`, `/v1/settings/audit`, `/v1/audit*` | missing |

### F. Product lifecycle, ops, and supporting surfaces

| Feature | Canonical authority | Workspace UI | API | CLI |
|---|---|---|---|---|
| Setup / install (wizard, presets, checklist) | `maistro-bootstrap` installer; Conductor setup service | supported — `Setup.tsx` POST `/v1/setup/complete`; onboarding gate | supported — `/v1/setup*`, `/v1/setup-checklist*` | supported — `maistro install` delegates to `maistro-bootstrap` (gated: `bootstrap` extra; [`cli/_install.py:11-29`](../../packages/maistro-core/src/maistro/cli/_install.py)); standalone `maistro-install` script |
| Upgrade | install manifest + upgrade paths (git/archive/package/container) | missing | missing | supported — `maistro upgrade` (tested per-install-type paths) |
| Settings (incl. features, volatile, reload) | Conductor settings service + `maistro` settings store | supported — `Settings.tsx` | supported — `/v1/settings*`; `unknown` on `/reload` (unresolved surface-truth disposition) | missing |
| Profile / audit log / quotas / metrics / optimizer / eval | per-domain services (see convergence matrix rows) | supported — `Profile.tsx`, `AuditLog.tsx`, `Quotas.tsx`, `OptimizationInbox.tsx` pages | supported — `/v1/profile`, `/v1/audit*`, `/v1/quotas*`, `/v1/dag-metrics`, `/v1/optimizer`, `/v1/eval-judge`, `/v1/harness` | partial — `maistro eval-workspace conformance` (#107 proof) |
| Canvas / Design Studio / Decks | `maistro-canvas`, `maistro-design` (optional router) | supported — `/design-studio`, `/decks`, `/cli/canvas` compat redirect ([:215](../../packages/hive-conductor/frontend/src/App.tsx)) | supported — BFF `/v1/canvas/*`, `/v1/design/*` (gated: degrades explicitly without the `maistro-design` package); server `/v2/canvas/*` | missing |
| Voice intent | Conductor voice service | supported — voice entry in chat shell | supported — `POST /v1/voice/intent` | missing |
| Widgets / messages / topology | Conductor projection services | supported — `MessageBoard.tsx`, `Topology.tsx`, dashboard widgets | supported — `/v1/widgets/*`, `/v1/messages*`, `/v1/topology*` | missing |
| CLI page (`/cli` mini console) | **no registered backend capability for its command set** | staged — page renders a fixed client-side command set ([CLI.tsx:42-69](../../packages/hive-conductor/frontend/src/pages/CLI.tsx)); backend `/v1/cli` manages sessions only ([routes/cli.py:11-18](../../packages/hive-conductor/backend/routes/cli.py)) | partial — `GET|POST /v1/cli/sessions` only | contract owner #292 (G4) |
| Dashboard TUI | none | — | — | staged — `maistro launch tui` prints an explicit placeholder ([_launch.py:39-43](../../packages/maistro-core/src/maistro/cli/_launch.py)) |
| ADR/spec registry tool | `maistro-registry` (repo governance, not product) | — | — | supported — `maistro-registry validate|walk|lint|generate` (out of product parity scope, listed for completeness) |
| Program context / persona interview | Conductor program service | supported — program/onboarding flows | supported — `/v1/program/*` incl. alias route `/v1/program/cpntext` ([:68-69](../../packages/hive-conductor/backend/routes/program.py); inventoried as observable, unchanged here) | missing |

## Horizontal control-plane concerns (issue AC-3)

| Concern | One-authority statement | Observable parity |
|---|---|---|
| Admission | Conduit/container front door → canonical receipt → Run; no second queue authority | UI Chat/Dashboard → BFF chat/tasks; server `POST /v1/tasks`; CLI has local Builders session only. Backpressure surfaced through shared chat/voice at base (#1182). |
| Authorization / refusal | Warden/Sentinel + workspace membership; refusals are server-side on all three surfaces (CLI is a client) | AuthMiddleware gates `/v1/*`; optional routers degrade loudly instead of disappearing silently ([backend/main.py:88-116](../../packages/hive-conductor/backend/main.py)). |
| Agent / tool selection | `agents.intents` routing table + `capabilities.governed_invocation` effect path; router/classifier are pure policy | Selection edits are UI/API-supported (section B); no CLI selection commands (gap rolled into P-3). |
| Run / effect identity | Canonical IDs (`run_id`, NodeRun, Attempt; Invocation on the effect path) end-to-end | All run routes key on canonical IDs; #1036 AC-8 requires the same scoped authority per surface — the rows above are the current answer key. |
| Inspect / control / retry / cancel | #1169 owns cancellation; #1036 owns the inspection/control seam | Cancel: API supported (both apps), UI/CLI missing. Retry: missing everywhere (P-2). Inspect: UI read-only, API supported, CLI missing. |
| Durable state | Convergence-matrix persistence owners (pg canonical, sqlite local, in-memory fallback) | UI/API read durable state; CLI durable reads are deliberately scoped to `maistro archive` (pre-convergence) and `maistro repair` (correction, with `--apply`). |

## Gap ledger (temporary gaps with verified owners)

| # | Gap | Owner | Release scope | Reason | Concrete next evidence |
|---|---|---|---|---|---|
| G1 | Builders has no API or UI counterpart; CLI TUI is gated on an extra | [#49](https://github.com/Agent-StrongHold/Project-mAIstro/issues/49) (defects #1067/#1068; proof [#459](https://github.com/Agent-StrongHold/Project-mAIstro/issues/459)) | M1 | Convergence first: execution must move to the canonical spine before projecting more surfaces | A shipped Builders composition constructs `CanonicalGraphPipelineExecutor` (not test-only) + #459 cross-product proof green |
| G2 | Evolve UI staged: route registered, nav-hidden | [#51](https://github.com/Agent-StrongHold/Project-mAIstro/issues/51) (children #1064/#1065/#1066) | v1.2 staging, preserved as approved 2026-10-03 | v1.0 hides Evolution until cycle publication is replay-safe and truthful | #1064/#1065/#1066 closed; nav restore is a v1.2 decision — **no interim compatibility layer** |
| G3 | RSI release scope is gated (separate package, optional router); one unresolved surface-truth row on `RSI.tsx` | [#50](https://github.com/Agent-StrongHold/Project-mAIstro/issues/50) | Existing gated scope, preserved | RSI becomes an ordinary canonical Run + work-source consumer in M5 | #50's work-source normalization; classification of the `RSI.tsx` unresolved row in `quality/shipped-surface-truth.json` |
| G4 | CLI page is a fixed client-side mini console over session-only backend routes | [#292](https://github.com/Agent-StrongHold/Project-mAIstro/issues/292) | M4 eventual (per that issue) | No contract defines the page's supported command set vs backend CLI sessions | #292's contract lands; page executes through registered backend capabilities or is renamed/scoped |
| G5 | Run inspection/control: UI is read-only (no cancel control), CLI has no inspect/control commands | [#1036](https://github.com/Agent-StrongHold/Project-mAIstro/issues/1036) (rich UX: #65; canonical cancel: #1169) | M1 seam, M3 UX | The control seam must read/delegate canonical truth before surfaces project controls | Cancel/control delegating to #1169 with repeat/refusal semantics; equivalent UI/API/CLI operations per #1036 AC-8 |

## Bounded missing-owner proposals (for review — not owners)

| # | Missing counterpart | Proposal |
|---|---|---|
| P-1 | HITL/capability approvals have API + CLI support but no Workspace UI caller | Owner review: fold a minimal approvals projection into the #65 UX plane or the capabilities service UI; do not create a separate approvals backend. |
| P-2 | Run retry exists on no surface | Owner review: define retry inside the #1169/#1036 control plane (a new Attempt under the same NodeRun/Run identity), or record it as a deliberate non-goal. |
| P-3 | No CLI commands for in-product CRUD (agents, providers, skills, MCP, schedules, backlog) | Owner review: decide whether CLI functional parity targets operator lifecycle only (today's state) or gains scoped CRUD; any addition goes through the existing public API authority, not new endpoints. |

These proposals raise no runtime work in this change; they exist so the missing rows above do not silently read as owned.

## Deliberately preserved decisions

- **Evolve UI v1.2 staging (approved 2026-10-03).** The `/evolution` route stays registered and nav-hidden; the v1.2 restore is recorded in [WORKSPACE-CUTOVER-PLAN.md](WORKSPACE-CUTOVER-PLAN.md) ([:467](WORKSPACE-CUTOVER-PLAN.md), [:508](WORKSPACE-CUTOVER-PLAN.md)). No interim compatibility layer is introduced to bridge it.
- **RSI's existing gated release scope.** Separate `maistro-rsi` package, optional `/v1/rsi` router, autorun script; nav entry presence does not change the release gate. Preserved unchanged.
- **Security boundaries.** AuthMiddleware scoping, the unauthenticated-by-design SPA fallback, explicit optional-router degradation, and every unresolved surface-truth disposition are reported here as-is; this matrix changes no permission, schema, or release date.
- **engine-092/093 and #292's browser CLI page** do not own the product CLI: the product CLI is the `[project.scripts]`/`maistro` Typer surface inventoried above; the `/cli` page is row F-G4 only.

## Boundaries of this document

No runtime implementation, service authority, UI, compatibility facade, schema, permission, or release-date change is made or proposed by this file. Milestones and issue states are untouched. Rows move only with executable evidence at a new commit.
