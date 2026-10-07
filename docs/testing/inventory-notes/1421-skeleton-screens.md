---
inventory-delta:
  packages/hive-conductor/tests/e2e: +0
---

# #1421 — structured skeleton screens for the bounded first-load surfaces

Three new Playwright specs join `tests/e2e/`, and one existing scenario in
`dashboard-metrics-states.spec.ts` is retargeted from the text sentence to
the skeleton it was asserting. The `+0` delta is literal: the e2e suite is
collected by pytest node ID (`check-suite-inventory.py`, bare python), and
`*.spec.ts` files are not pytest-collectible — the suite's collected count
is unchanged, as in the #359 note.

## Route/component mapping (bounded surfaces, per the issue)

| Surface | Route | Component | Pending read(s) |
|---|---|---|---|
| Dashboard / Workspace Home | `/dashboard` | `frontend/src/pages/Dashboard.tsx` | `GET /v1/dashboard/layout` (grid skeleton), `GET /v1/dashboard/metrics` (per-KPI skeleton) |
| Workspace selection | app toolbar | `frontend/src/components/WorkspaceTabs.tsx` + `frontend/src/context/WorkspaceContext.tsx` | `GET /v1/workspaces` (tab-strip skeleton, error-with-retry), `GET /v1/workspaces/persona-templates` (persona-picker skeleton) |
| Workspace Backlog | `/backlog` | `frontend/src/pages/Backlog.tsx` | `GET /v1/backlog` (board/list skeletons, error banner + retry), `GET /v1/backlog/{id}` (detail-modal skeleton, stale-answer guard) |

Workspace Home (#1048) has not replaced `Dashboard.tsx`; per the issue the
retained Dashboard is covered and not redesigned.

## Surface/state matrix

| Region | pending | populated | empty (settled) | error / auth | stale |
|---|---|---|---|---|---|
| Dashboard grid | `dashboard-skeleton` (aria-busy, `role=status`, aria-hidden shapes) | widget cards replace it | server layout empty → defaults saved (existing behavior) | 401/500/transport → default widgets, never a permanent skeleton | single-shot read on mount; nav-away covered |
| Dashboard KPI body | `kpi-loading` (aria-busy body, sized value/sub/footer shapes) | measured value, busy cleared | `Unknown KPI … did not report it` | 401 → sign-in state; other failures → outage state (existing, still pinned by `dashboard-metrics-states.spec.ts`) | metrics single-shot per mount |
| Workspace tab strip | `workspace-tabs-skeleton` (aria-busy, sized pills; was `null`) | named tabs | `workspace-empty` copy | 401/500/transport → `workspace-tab-error` with Retry | superseded `refresh()` answer dropped by sequence guard |
| Persona picker | `persona-skeleton` (aria-busy rows; was "No personas available") | named options + taglines | `No personas available` (settled only) | read fails → same settled degraded copy | picker re-reads on each open |
| Backlog board/list | `backlog-skeleton` (aria-busy; was four "empty" columns + "0 items") | cards/rows | genuine empty copy | 401/500/transport → `backlog-load-error` alert with Retry | retry keeps a loaded board on failure |
| Backlog detail modal | `backlog-detail-skeleton` (aria-busy; was prior item's content) | item fields + edit form | n/a (id always exists when opened from a card) | read fails → toast + modal closes (existing) | late answer for a superseded open dropped by sequence guard |

All shapes are `aria-hidden` and unfocusable; `prefers-reduced-motion` keeps
the shared `.skeleton` pulse disabled (the existing guarded media block).
Screenshots land in `test-results/skeleton-evidence/{dashboard,workspace-tabs,backlog}/`
(gitignored) from every run.
