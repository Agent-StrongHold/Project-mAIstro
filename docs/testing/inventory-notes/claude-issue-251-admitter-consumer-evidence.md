---
inventory-delta:
  packages/maistro-core/tests: +1
---
# claude-issue-251-admitter-consumer-evidence

Adds one end-to-end acceptance test proving the Container's production
`ScheduleRunAdmitter` admits a queued canonical Run that the Container consumer
tick executes to completion with canonical NodeRun and Attempt records.
