---
inventory-delta:
  tests/: +32
---

# Autonomous merge safety gate tests

Adds 32 root-suite tests for the base-trusted autonomous merge classifier and
ratchets: agent identification, green/yellow/red classification, trusted CI and
eval paths, rename handling, test deletion/suppression detection, merge-group
behavior, fail-closed git errors, and the JSON report path.
