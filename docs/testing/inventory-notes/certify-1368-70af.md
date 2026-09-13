---
inventory-delta:
  tests/: +4
---
# certify-1368-70af

The four added `tests/` node IDs are intentional regression coverage for
`check-gates-ran.py`: malformed and non-object changed-file evidence both fail
closed, while loaderless and loadable scope-classifier specs respectively
degrade to pending and preserve the normal classification path.
