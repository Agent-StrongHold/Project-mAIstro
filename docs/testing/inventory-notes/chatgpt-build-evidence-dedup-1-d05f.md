---
inventory-delta:
  tests/: +9
---
# chatgpt-build-evidence-dedup-1-d05f

All nine new node IDs are `tests/test_build_evidence.py`, added alongside
`scripts/build-evidence.py`: the fail-closed content-addressed build-evidence
identity primitive for the build-efficiency program (#654). They cover
input-order independence, content/command sensitivity, stable directory
hashing, deduplication of overlapping inputs, and the three fail-closed
cases (missing input, empty directory, input outside the repository root)
plus an empty command. No existing test moved or was removed.
