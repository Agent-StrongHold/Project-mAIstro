---
inventory-delta:
  packages/maistro-core/tests: +8
---
# auto-1090-f6ba

The delegation admission work on this branch contributes eight collected node
IDs for reservation, receipt, retry, and cross-replica fault boundaries. The
stable parent NodeRun identity regression also exercises a changed retry
payload, proving it cannot create a second child or task.

The delta was re-recorded after the 2026-09-17 rebase onto develop
(`044c6ac7`): the review round replaced the uncertain-transport completion
with a timer-resumable `awaiting_delegation_reconciliation` pause and its
poll/expiry/adopt regression tests, authenticated guest-peer reconciliation,
and the losing-reservation rollback, for a net of eight tests over the folded
baseline (the previously recorded +9 no longer matched what the tree
collects).
