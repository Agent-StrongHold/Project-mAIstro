---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
  packages/maistro-core/tests: +2
---

# 1333-concurrent-scoped-run-lookups

Issue #1333: the Recent Runs list overlaid canonical lifecycle truth with one
sequential `await` per row, each row costing a canonical `RunStore.get_run`
round trip — up to 100 serialized reads per dashboard request at the page cap
over a durable store. The batched-reader repair from #1152 had already routed
the page through `ScopedRunReader.get_runs`, but that reader still resolved the
page's per-Run lookups one `await` at a time.

The fix overlaps the page's independent `_lookup_run` calls with a bounded
`asyncio.gather` (16 in flight) before the once-per-scope authorization
decisions, so the visible-Runs answer, its dedup/order, and its
unreadable-run-as-missing refusals are unchanged.

Two test movements:

- `packages/maistro-core/tests/runs/test_scoped_reads.py` (+2 across the
  memory/sqlite parametrization): a counting store records how many `get_run`
  reads ever overlap while a four-id page (one foreign, one missing, one
  duplicate) resolves. The counter suspends inside every read — an async def
  with no await point runs to completion inside a gather and would pin
  nothing — so the assertion `max_in_flight >= 2` fails against the
  sequential regression (observed: 1) and holds under the gather. It also
  pins that the duplicate costs one store lookup, not two, and that every
  read settles.
- `packages/hive-conductor/backend/tests/test_dag_run_cancel_route.py` (+1):
  the endpoint-side companion pins that `list_visible_runs` re-enters the
  canonical reader exactly once for the whole page, carrying both canonical
  ids in that one batch — the property whose loss would rebuild the per-row
  walk this issue closed.
