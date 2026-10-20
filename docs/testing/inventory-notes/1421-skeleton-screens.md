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
skeletons, not blank regions). `scripts/check-suite-inventory.py` passes on
the merged tree. `scripts/check-frontend-typed-client.py` does **not**: on
the develop-merged tree it reports 45 problems, because #1421 shifted the
line numbers of 15 debt rows the ratchet banks by line (see the repair
round below).

## Salvage round 2026-10-18 (empty-state opener)

Every persona-picker case above drove the "+" tab, but a first-run account
reaches the create form through the empty state's "Create workspace" button —
an opener that set `creating` without raising `templatesPending`, so the
form's first paint showed "No personas available" for a read that had not
answered. `WorkspaceTabs.tsx` now routes both openers through one
`openCreate()` that raises the flag before the form can paint, and
`workspace-tabs-skeleton.spec.ts` pins it with "opening the form from the
empty state shows the persona skeleton, not the degraded copy".

The delta stays `+0` (a case added to an existing non-pytest-collectible
spec); the harness total is now 27 tests (9 tabs + 7 dashboard + 7 backlog).
All 27 pass locally against the worktree (`E2E_SRC_ROOT`/`E2E_NODE_PATHS`
pointed at it, `tests/e2e`'s own playwright 1.60 + chromium). The new case
was shown to fail against the pre-salvage component —
`getByTestId('persona-skeleton')` never visible after the empty-state click —
while the other 8 cases in its spec still passed, so it pins this regression
rather than passing for an environmental reason. Frontend `npm run lint`
(94 warnings ≤ the 96 budget, 0 errors) and `npm run build` (both tsconfigs +
vite) pass; `scripts/check-suite-inventory.py` and
`scripts/check-frontend-typed-client.py` pass on the tree.

## Repair round (ratchet repair + the two open review findings)

The develop merge left the frontend typed-client ratchet red: it banks debt
**by line number**, and #1421's edits to `frontend/src/pages/Dashboard.tsx`
moved 15 banked rows (13 `raw_fetch`, 2 `hand_typed`) to new lines, so the
gate saw 13 "NEW frontend typed-client debt absent from the trusted base",
2 "current violation missing from the candidate ledger" and 30 "fixed --
delete it from the candidate ledger" problems while the totals (56 raw
fetch / 136 hand-typed) were unchanged. The repair keeps every banked row
on its original line instead of touching
`quality/frontend-typed-client-baseline.json` (no ledger or grant edits in
an implementation change): the hook reports settlement through a callback
(`useServerTabs(..., onSettled)`) rather than through state the page owns
differently, the pending-state ternary and both skeleton components are
laid out so the debt rows keep their line numbers, and the two skeleton
components moved to the end of the file (after the last banked row).

Two findings from the PR review are closed here as well:

* **P1 — a hung layout/metrics read pinned the skeleton forever.** Both
  reads now carry the shared client's 30 s budget
  (`lib/api.ts` `DEFAULT_TIMEOUT_MS`), applied through a `boundedRead`
  helper at the end of `Dashboard.tsx` (`AbortController` + `setTimeout` +
  `clearTimeout`, the house pattern; no `AbortSignal.any`, so the build's
  browser baseline holds). A stalled read therefore ends the pending state
  and the page settles into the long-standing default dashboard.
* **P2 — a retry could restore a stale board.** The board read in
  `Backlog.tsx` now carries a sequence number (`loadSeq`), the same
  `WorkspaceContext` pattern, so only the newest read may commit.

Two cases were added to the two specs (the e2e suite stays non-pytest-
collectible, so the delta is still `+0`):

* `dashboard-skeleton-loading.spec.ts` — "a stalled layout read cannot pin
  the skeleton forever": the harness holds the layout read open and the
  test crosses the read's budget with Playwright's clock
  (`page.clock.install()` / `fastForward(31_000)`), then asserts the
  skeleton is gone and the default board is back. Shown to fail against the
  unbounded read (`dashboard-skeleton` still visible after the budget).
* `backlog-skeleton-loading.spec.ts` — "a retry that answers after a newer
  one cannot restore the older board": two board reads are in flight at
  once, the newer answers first, and the older answer must not replace the
  board. The two reads are answered by an in-browser `page.route` (the
  workspace-tabs spec scripts its stale refresh the same way): over the
  real socket the browser pipelines a second request to the same URL
  behind the first, so two reads to `/v1/backlog` could never overlap on
  the wire. Shown to fail against the unsequenced read ("Stale board
  item" back on screen).

Local evidence: 36/36 harness tests pass across the four #1421 skeleton
specs (dashboard 10, metrics 7, backlog 10, tabs 9), and the same 20
dashboard+backlog tests pass under the CI image's Playwright 1.52 as well
(the local run uses 1.60). The full local e2e suite is 192 passed / 4
failed, and the four failures are live-backend environment failures
(`CanonicalGraphUnavailable` in `pm-workflow.spec.ts`, plus one
credentials-draft case) that touch none of the surfaces above. Frontend
`npm run lint` (94 warnings ≤ the 96 budget, 0 errors), `npm run build`
(both tsconfigs + vite), `npx tsc --noEmit`,
`scripts/check-frontend-typed-client.py` (56 raw fetch / 136 hand-typed,
none new) and `scripts/check-vulture-baseline.py` all pass.
