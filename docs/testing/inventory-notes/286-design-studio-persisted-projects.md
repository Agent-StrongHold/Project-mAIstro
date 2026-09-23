---
inventory-delta:
  packages/hive-conductor/backend/tests: +4
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
tests, so the honest net for this change is +4: 7 route tests added, 3 removed.
