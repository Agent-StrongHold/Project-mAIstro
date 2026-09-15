---
inventory-delta:
  packages/maistro-core/tests: +2
---
# claude-issue-251-admitter-consumer-evidence

Adds end-to-end acceptance tests proving the Container's production
`ScheduleRunAdmitter` admits queued canonical Runs that the Container consumer
tick executes to completion with canonical NodeRun and Attempt records on both
in-memory and claim-capable SQLite wiring.
