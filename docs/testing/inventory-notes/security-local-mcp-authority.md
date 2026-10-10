---
inventory-delta:
  packages/hive-conductor/backend/tests: +14
---

# Validate local MCP authorities

Adds 11 no-network negative URL cases and three supported loopback URL cases.
The focused MCP client suite passes 42 tests. Against the unmodified source,
10 of the 11 negative cases fail by attempting HTTP client construction;
userinfo on the true local host was already rejected by the old prefix check.

The repair parses the authority and rejects lookalike hosts, userinfo,
malformed/out-of-range ports, and control/backslash ambiguity. Existing HTTP
localhost/127.0.0.1 behavior remains supported. No scanner suppression is added.
