---
inventory-delta:
  packages/maistro-core/tests: +19
---
# auto-1090-f6ba

The delegation admission work on this branch contributes nineteen collected
node IDs for reservation, receipt, retry, and cross-replica fault boundaries.
The stable parent NodeRun identity regression also exercises a changed retry
payload, proving it cannot create a second child or task.

The delta was re-recorded after the 2026-09-17 rebase onto develop
(`044c6ac7`): the review round replaced the uncertain-transport completion
with a timer-resumable `awaiting_delegation_reconciliation` pause and its
poll/expiry/adopt regression tests, authenticated guest-peer reconciliation,
and the losing-reservation rollback. The receipt machinery the review surfaced
(find/attach receipt, transport-claim CAS) is now proven on all three spine
backends — memory, SQLite, PostgreSQL — which is what the diff-coverage floor
was reporting as untested pg arcs.
