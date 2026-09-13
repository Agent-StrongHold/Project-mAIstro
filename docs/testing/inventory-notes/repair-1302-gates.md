---
inventory-delta:
  packages/maistro-core/tests: +1
---
# PR #1302 gate-repair coverage

Added one regression test to `test_container_wiring.py` for the PostgreSQL capability-ledger branch. It asserts that the production container's dynamic `PgEventStore` path is executable and returns the canonical event store rather than leaving the import as untested reachability debt.

The repair also prunes the now-reachable `maistro.events.pg_envelope` entry from the reachability baseline/disposition pair, records the measured `llm.summarize` complexity reduction (18 → 11), and replaces insecure fake HTTPS endpoints in the newly added egress tests so DevSkim no longer reports them.
