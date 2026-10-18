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

## Validation round 2026-10-18 (develop sync + CI-image repairs)

Re-validated the three harness specs inside the actual
`tests/Dockerfile.playwright` image (the `hive-conductor-e2e-ui` execution
mode) after syncing develop (b1f17b8d, then 35a72ff54). Three evidence-driven
repairs, no test-count change (delta stays `+0`):

1. The image never copied `frontend/src/index.css`, so every spec serving it
   failed with `ENOENT` before a page could load. The Dockerfile now ships it.
2. Serving `index.css` alone still painted transparent, unstyled shapes: the
   file only binds token names, and `.skeleton`'s `background: var(--rule)`
   resolves only once the theme files are in the cascade. The harness routes
   now serve the shipped order — `themes/workspace-tokens.css` →
   `themes/workspace-bridge.css` → `index.css` (main.tsx's import order) — and
   the Dockerfile copies both theme files. The loading screenshots show the
   real styled placeholders (verified visually at desktop and narrow widths).
3. `backlog-skeleton-loading.spec.ts`'s failed-detail-read scenario scripted
   an immediate 500, so the modal closed before the skeleton ever painted and
   the `toBeVisible` assertion raced it (reproduced in-image). It now holds
   the read open, asserts the skeleton, releases into the failure, and mounts
   its own board from a freshly scripted list read, so it also passes when run
   alone.

Evidence: 26/26 harness spec tests pass in the final image; the two
backend-dependent specs (`template-picker-skeleton`, `app-shell-loading`) pass
5/5 against a live hive container; screenshot pairs land at desktop and
narrow widths (loading vs resolved differ; loading frames show the styled
skeletons, not blank regions). `scripts/check-suite-inventory.py` and
`scripts/check-frontend-typed-client.py` both pass on the merged tree.
