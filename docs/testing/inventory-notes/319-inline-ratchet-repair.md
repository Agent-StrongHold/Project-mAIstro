---
inventory-delta:
  tests/: +7
  scripts/: +2
  quality/: +1
---
# Issue 319 inline ratchet repair

The workflow floors for aggregate and diff coverage, Xenon, Pyright and
Interrogate now live in one versioned quality baseline. Their checkers resolve
that baseline from the trusted merge base and print the base/candidate/tool
provenance record. Inventory tests reject numeric YAML thresholds and cover the
mutation where a candidate weakens a measurement while editing its baseline.
