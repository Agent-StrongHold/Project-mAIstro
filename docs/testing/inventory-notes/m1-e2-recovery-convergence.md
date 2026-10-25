---
inventory-delta:
  packages/maistro-core/tests: +12
---
# M1-E2 recovery convergence

Adds behavioral coverage for the #1192 pause-reason-to-waker registry, external
completion writes for system-owned WAITING Graph pauses, and #1151 replay of a
parent Run after canonical NodeRun settlement. The repair adds mechanical waker
resolution and cross-instance peer polling coverage.
