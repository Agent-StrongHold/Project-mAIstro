---
inventory-delta:
  packages/maistro-core/tests: +6
---

# Authorized agent list/select/claim/write (#102)

`packages/maistro-core/tests/backlog/test_agent_surface.py` is new: 6 node
IDs for `maistro.backlog.agent_surface`, the fail-closed agent work path the
cutover acceptance requires against the DB. Listing hides closed work and
requires a read role; selection is deterministic (priority, then rank, then
age) and skips claimed items; the claim/write/release cycle attributes every
change, refuses a bystander's write under someone else's lease, refuses a
second claim while a lease is live, and lets editors write once no claim is
held; viewers read but cannot claim or write; unknown items and foreign
workspaces answer with the same not-found semantics (no existence oracle).
The SQLite leg runs the full cycle across a restart: item, edit, live lease
and event history (`created, claimed, updated`) all survive on a fresh
connection. No existing test was removed or renamed.
