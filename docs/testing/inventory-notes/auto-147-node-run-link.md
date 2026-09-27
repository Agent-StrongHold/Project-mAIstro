---
inventory-delta:
  packages/maistro-core/tests: +1
---
# auto-147 NodeRun link

Adds a regression proving store-backed remote delegation refuses a context
without its admitting `node_run_id` before the A2A task is dispatched. This
keeps every accepted child Run correlated to the parent NodeRun rather than
creating an orphaned child with only a parent Run link.
