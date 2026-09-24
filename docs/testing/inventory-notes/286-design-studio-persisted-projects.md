---
inventory-delta:
  packages/hive-conductor/backend/tests: +7
  packages/maistro-design/tests: +1
---
# Design Studio persisted project readback

Adds browser regressions for the Design Studio parent surface: one supplies a
persisted-project response and verifies that durable project/output facts render
without presenting them as visual generation, while the other verifies that a
503 persistence response is shown as unavailable rather than as an empty
project list. Backend route tests cover both disabled and uninitialized stores for project
listing/rendering, prove project preparation fails closed without persistence,
and prove persisted output readback includes content and provenance. In-scope
render creation and polling fail with 501 rather than creating or reading
process-local jobs; the existing unavailable-generation and no-timer assertions
remain in the same scenario. Design package coverage locks the output API
serializer to prompt-preparation semantics rather than visual-generation claims.
The browser specs are Playwright files and do not change the pytest collection
count recorded for this suite.

The +7 originally recorded here assumed the first cut of the render-route
tests. The route-conflict fix then replaced the three process-local
preview-job tests (`refuses_before_any_probe`,
`reports_unavailable_without_creating_a_pending_job`,
`polling_render_status_reports_unavailable`) with scope-carrying 501/503 route
tests, so the honest net was +4: 7 route tests added, 3 removed. A later
CI repair for the diff-coverage gate added three more route tests, taking the
net to +7: an out-of-scope render-poll id answers the same scoped 404 (polling
is disabled but not an id probe), a store read that fails while polling is an
explicit 500 rather than a fabricated job state, and an unexpected crash inside
project preparation is a 500 whose message names preparation, not generation.
