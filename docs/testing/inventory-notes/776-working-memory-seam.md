---
inventory-delta:
  packages/maistro-core/tests: +26
---

# 776 — per-Workspace working-memory seam (M3 product floor)

Issue #776 adds the minimum per-Workspace Ladybug working graph
(ADR-082226-5104): a disposable, non-authoritative projection of durable
memory that the persistent Workspace Agent can hydrate lazily, query, discard
and rebuild, under `maistro.memory.working_graph`.

The 26 new `packages/maistro-core/tests/memory/working_graph` node IDs cover
the acceptance properties that make the seam real rather than a claimed
abstraction:

- hydration happens lazily on first use, from the engine's **real** in-process
  episodic and learning stores, and is bounded;
- retrieved context retains canonical references (memory/learning/artifact/
  run/node_run/attempt/project/goal/workspace ids), including in the rendered
  text a consumer would paste into a prompt;
- a durably recorded user correction becomes visible only through
  hydration/refresh — the projection never invents it early and never invents
  facts on an empty graph;
- accepted and rejected artifact versions hydrate with lineage and
  produced-during linkage;
- Run provenance keeps Goal and parent-Run linkage, and one traversal hop
  reaches a memory's producer Run and its parent (the transcript linkage
  Dreaming will consume under #301/#1047);
- two Workspaces with colliding identifiers — even served by one manager and
  one source — never observe or traverse each other's graph; a backend refuses
  a foreign Workspace's records, and a mis-scoped hydration source is refused
  loudly instead of poisoning a graph;
- discard/rebuild loses nothing durable (durable reads re-verified unchanged);
- a broken backend reports UNAVAILABLE and a partially failing source reports
  DEGRADED, with the reason surfaced in `GraphContext`/`WorkingMemoryStatus`,
  while durable reads still succeed;
- manager lifecycle: one graph per Workspace identity, LRU eviction disposes
  (closes) the least recently used graph, `discard_all`, and explicit
  refusal of blank Workspace ids.

Nothing was removed: this change is purely additive, and no existing node IDs
moved. The suite grew by exactly the 26 new tests; the durable memory suites
they sit beside are untouched (438 collected in `tests/memory` after the
change, all passing).
