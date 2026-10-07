# Route / entry-point inventory (#1417)

Reconciles the registered SPA route table with the entry points that reach
each destination, per the clarified scope of
[#1417](https://github.com/Agent-StrongHold/Project-mAIstro/issues/1417).
Recorded at implementation commit `auto-1417` (base `b0912ce590d51bcfe4944da57770575e50ae2e8a`).

Sources of truth:

- Routes: `frontend/src/App.tsx` (the only `Route` registration site).
- Entry points: `frontend/src/components/AppShell.tsx` (`fullNav`, rendered as
  both the desktop icon rail and the narrow-screen drawer), the drawer user
  chip, and contextual links inside pages.
- Dispositions: [WORKSPACE-CUTOVER-PLAN.md](../../docs/architecture/WORKSPACE-CUTOVER-PLAN.md)
  §5 retirement ledger and §9 v1.0 stakeholder amendments; [ROADMAP.md](../../ROADMAP.md).

## Change made by #1417

Six retained shipped surfaces had no entry point anywhere in the app
(`/schedules`, `/messages`, `/quotas`, `/containers`, `/cli`, `/audit`). They
now have `fullNav` entries. `/optimization-inbox` became a redirect to the
canonical `/optimizer` so an alias hit resolves to the one nav-linked
destination instead of rendering a second active-state-less copy of the page.
The legacy pages scheduled for replacement by Workspace projections were
deliberately **not** promoted (per §9 and the issue boundary); they are
recorded below as URL-only with their owning issues.

## Canonical surfaces (primary/grouped navigation entry)

21 destinations, each reachable from both the desktop icon rail and the
narrow-screen drawer (asserted by
`tests/e2e/navigation-coverage.spec.ts`):

| Route | Surface | Nav label | Disposition (cutover plan §5/§9) | Replacement owner |
|---|---|---|---|---|
| `/chat` | Chat | Chat | PROJECT → Workspace Agent chat | #1037 (M3-D) |
| `/dashboard` | Dashboard | Dashboard | DELETE v1.0 → Workspace Home | #1048 |
| `/design-studio` | Design Studio | Design Studio | KEEP / PROJECT v1.0 (blocker) | #95, #286, #773 |
| `/dags` | DAG Builder | DAG Builder | PROJECT → Graph editing over canonical Graph | #65/#1036 |
| `/dag-runs` | DAG Runs | DAG Runs | PROJECT → Goal/Run inspection | #65/#1036, #251 |
| `/schedules` | Schedules | Schedules | PROJECT → canonical `ScheduleStore` | #92 (M3-B) |
| `/missions` | Missions | Missions | MERGE → Workspace backlog (DELETE v1.0) | #82 (M3-C) |
| `/backlog` | Backlog | Backlog | Workspace backlog (canonical) | #82 |
| `/agents` | Agents | Agents | DELETE v1.0 → Capabilities projection | #59, #848 |
| `/topology` | Topology | Topology | DELETE v1.0 → Capabilities projection | #59, #848 |
| `/optimizer` | Optimization Inbox | Optimizer | MERGE → Attention/Waiting | #1049 (M3-E) |
| `/messages` | Message Board | Messages | MERGE → Attention/Waiting | #1049 (M3-E) |
| `/quotas` | Quotas & Stats | Quotas | PROJECT → Invocation usage | #718 (M3) |
| `/knowledge` | KnowledgeBase | Inner Temple | DELETE v1.0 → Workspace/user memory | #776, #1047 (M3-E) |
| `/rsi` | RSI | RSI | PROJECT → Evolve/RSI Run inspection | #51/#50 (M4/M5) |
| `/mcp` | MCP | Integrations | DELETE v1.0 → Capabilities projection | #59, #848 |
| `/containers` | Containers | Containers | PROJECT v1.0 (retained contract) | #382 |
| `/cli` | CLI | CLI | PROJECT v1.0 (retained contract) | #292 |
| `/credentials` | Credentials | Credentials | PROJECT → credential router consumers | #58 |
| `/audit` | Audit Log | Audit | PROJECT → core audit store | P0.4 (§5) |
| `/settings` | Settings | Settings | PROJECT → settings service | #1050 (M3-E) |

`/schedules`, `/messages`, `/quotas`, `/containers`, `/cli` and `/audit` are
the #1417 additions. The legacy rows already linked before #1417 (Chat,
Missions, Agents, Topology, Optimizer, KnowledgeBase, MCP) keep their entries:
removing them is the retirement work of the owning issues, not a
discoverability change, and dropping their links now would orphan live routes.

## Canonical surfaces with a contextual or parent entry (no primary nav row)

| Route | Surface | Entry point | Disposition | Owner |
|---|---|---|---|---|
| `/profile` | Profile | Drawer user chip (`NavLink` on the signed-in username) | PROJECT → settings service | #1050 |
| `/docs` | Documentation | `helpHref="/docs#…"` contextual link rendered by `PageHeader` on most pages (Schedules, Skills, Topology, Messages, Quotas, Audit, Containers, Agents, Missions, Evolution, MCP, Optimizer, Settings, CLI) | RETIRE (M3) | cutover plan §5 |
| `/decks` | Deck Builder | Embedded editor inside Design Studio (deck mode → "Open Deck editor"); the standalone route is the deep link to the same editor | KEEP (own lane) | #286, #773, #95 |

## Intentionally URL-only surfaces (documented exception)

These render at their route but get no navigation entry, because §9 replaces
or hides them and this issue may not promote or retire them:

| Route | Surface | Rationale for staying unlinked | Owner |
|---|---|---|---|
| `/work-items` | Jira drafts (WorkItems) | Legacy surface MERGEd into the Workspace backlog; permanent promotion would fight the M3-C cutover | #82 (M3-C) |
| `/skills` | Skills | Legacy surface replaced by the Capabilities projection | #59, #848 (M3) |
| `/memory` | Memory | Legacy surface replaced by user model / Workspace memory | #776, #1047 (M3-E) |
| `/evolution` | Evolution Engine | Hidden for v1.0 per §9 ("DELETE/HIDE v1.0, restore v1.2"); route retirement itself is out of #1417's scope | cutover plan §9 (v1.2) |

`tests/e2e/navigation-coverage.spec.ts` asserts both halves of this contract:
these routes still render (they are not deleted) and the shell renders no nav
link for them.

## Aliases, redirects, default routes

One canonical entry per destination; no duplicate menu items.

| Route | Resolves to | Kind |
|---|---|---|
| `/` | `/dashboard` (index `Navigate replace`) | default-route redirect |
| `/optimization-inbox` | `/optimizer` (#1417: alias converted from a duplicate render to a redirect) | alias redirect |
| `/cli/canvas` | `/design-studio` (#95 compatibility redirect; asserted by `tests/e2e/design-studio-truthfulness.spec.ts`) | compatibility redirect |

## Auth / setup routes (outside the shell)

| Route | Surface | Kind |
|---|---|---|
| `/setup` | Setup wizard | auth/installer (KEEP) |
| — | Login | rendered by `AuthGuard` when unauthenticated (KEEP) |

## Permission contract check

All six routers behind the newly linked pages (`/v1/schedules`,
`/v1/messages`, `/v1/quotas`, `/v1/containers`, `/v1/cli`, `/v1/audit`) are
available to every authenticated principal: they carry no admin or elevation
dependency (the only `require_admin` checks in the backend are user-management
endpoints in `routes/auth.py`), so the unconditional nav entries imply no
access an ordinary principal lacks. Scoped-principal navigation filtering is
the #1048 navigation work; nothing here substitutes for backend
authorization, and no entry was added for a surface a principal class cannot
reach.

## Verification

- `tests/e2e/navigation-coverage.spec.ts` — every nav row above is reached
  from the rail (desktop, keyboard activation) and the drawer (narrow
  viewport, keyboard activation + dismissal); each lands with exactly one
  active rail entry carrying the destination's accessible name; back/forward
  returns canonical surfaces; the two aliases/redirects resolve to their
  canonical destination; the four URL-only rows render while staying unlinked.
- `tests/e2e/design-studio-truthfulness.spec.ts` — `/cli/canvas` compatibility
  redirect preserved.
