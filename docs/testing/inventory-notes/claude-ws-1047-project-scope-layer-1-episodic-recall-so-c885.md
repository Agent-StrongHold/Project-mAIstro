---
inventory-delta:
  packages/maistro-core/tests: +68
---
# Project-scoped layer-1 episodic recall (#1047, partial)

Sixty-eight new node IDs, all additions, none removed. Refreshed against
current develop with the working-memory hot path and explicit memory exposure
authority retained.

- `tests/memory/test_context_assembly.py::TestLayer1IsProjectScoped` (+62):
  in-memory and SQLite authoritative stores, directly and through the real
  working projection. Named projects isolate one agent's memories across
  projects on ranked and unranked paths; an empty project preserves legacy
  recall; unattributed memories (including unbound globals) cannot enter a
  named project; whitespace and unknown projects remain exact filters; the
  project filter does not replace agent scope. ContextBuilder composition
  confirms the correct project reaches the final memory prompt block.
- `tests/memory/test_ranked_recall.py::TestRankingGoesThroughTheProtocol::test_layer1_sends_the_project_to_the_store`
  (+2): both durable recall paths hand the project to the store rather than
  filtering after the read.
- `tests/memory/working/test_working_context_layers.py::TestLayer1HotPath`
  (+4): real hot recall passes both agent and project axes, hydration/read
  failures retain project-scoped durable fallback, and an empty healthy hot
  result never triggers a wider fallback.
