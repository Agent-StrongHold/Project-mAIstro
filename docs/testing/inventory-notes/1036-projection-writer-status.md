---
inventory-delta:
  packages/hive-conductor/backend/tests: +36
---
# #1036: preserve canonical-derived status in both projection writers

Adds 36 behavioral cases, without replacing existing coverage:

- 18 cases exercise both the HTTP writer and the actual WebSocket route's
  result callback over every canonical RunStatus. Five nonterminal statuses
  remain exact with no finished_at; four terminal statuses retain the existing
  finish behavior. Each persists/reopens the existing Hive presentation cache
  (State/PersistedStore/JsonStore) and inspects list/detail with the canonical
  reader absent and separately raising. This is projection reopen evidence,
  not canonical PostgreSQL recovery proof or a new SQLite compatibility path.
- 16 malformed/missing status cases cover both writers with and without an
  existing projection. No start/event/finish/result mutation is invoked;
  existing durable records remain identical and the failure is logged.
- One live WAITING-to-COMPLETED case retains event sequences and buffered
  replay across reopen. A late nonterminal result does not rewrite the
  finished row, preserving the existing first-terminal-write behavior.
- One presentation-store boundary case rejects terminal/unknown statuses at
  the additive nonterminal-result method and leaves missing rows absent.

Before implementation, the original 34-case writer matrix produced 18
failures and 16 passes against develop ab8b3737fa64f8d840f421ef87ca506c509444ff.
After implementation, the focused eight-suite regression run passed 189
cases, including existing canonical timestamp/overlay, cancellation,
transport parity, cross-Workspace visibility and history/replay tests.

The projection has no revision/order token. This change does not invent an
ordering policy for intermediate snapshots, multi-replica freshness, or
repeated HTTP start semantics. Readable canonical state still overlays it.
Historical visibility, reader failure policy, canonical stores, controls and
no-projection lookup are unchanged. Broader #1036 acceptance remains open.
