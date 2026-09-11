---
inventory-delta:
  tests/: +7
---
# repair-m1-1144-shipped-surface-discovery

Added regression coverage for the repair:

- positional Starlette `add_route` method discovery;
- conditional effect paths and effect evidence on every branch;
- statically visible `gateway.post` frontend wrapper discovery;
- Starlette route decorators/objects and no-op return-path regressions, including logger builder chains and no-op loops.
