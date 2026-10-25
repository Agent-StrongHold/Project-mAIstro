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
  memory/sqlite parametrization): a counting store records how far `get_run`
  reads ever overlap while a four-id page (one foreign, one missing, one
  duplicate) resolves, in two windows. `dispatched` brackets the real store
  call — a second increment can only land while an earlier read is suspended
  inside the store, at its own aiosqlite await — and is asserted `>= 2` for
  the sqlite parametrization; `scheduled` counts reads set in motion before a
  cooperative yield, the deepest window the memory store offers, whose
  `get_run` is a synchronous dict hit with no await point of its own. Both
  assertions fail against the sequential regression (observed: 1) and hold
  under the gather. It also pins that the duplicate costs one store lookup,
  not two, and that every read settles.
- `packages/hive-conductor/backend/tests/test_dag_run_cancel_route.py` (+1):
  the endpoint-side companion pins that `list_visible_runs` re-enters the
  canonical reader exactly once for the whole page, carrying both canonical
  ids in that one batch — the property whose loss would rebuild the per-row
  walk this issue closed.
