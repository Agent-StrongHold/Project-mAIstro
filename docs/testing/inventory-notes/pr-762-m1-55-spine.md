---
inventory-delta:
  packages/maistro-core/tests: +11
---
# pr-762-m1-55-spine

M1-D1 governed Invocation spine (#55, PR #762). The repair commit 432e5e79
added 11 net node IDs to `packages/maistro-core/tests`:

- `tests/capabilities/test_binding_invocation.py` (new file): focused tests
  for the previously uncovered `InMemoryBindingStore` arcs — immutable
  re-put, blank scope fields, unregistered id, project/node/capability
  mismatch, unrestricted-node pass-through.
- `tests/graph/nodes/test_agent_spawn_harness.py`: dispatch-guard arcs
  (foreign provider type, non-dict invocation result, invalid dispatch
  handle) plus governed-path coverage.
- `tests/test_container_wiring.py` / `tests/graph/nodes/test_rsi_quota_pace_trigger.py`:
  switched from the removed ungoverned dispatch path to the governed
  binding_id + registered Binding contract; net count change on these two
  files is small (additions and removals nearly cancel).

No suite silently stopped collecting — every one of the 11 IDs is a test
the spine wiring intentionally added; the full suite still collects 9375.
