---
inventory-delta:
  tests/: +1
---
# Issue #751 deterministic validator repair

Adds regression coverage proving the validator uses the registry's declared `as_of` snapshot and
never reads the wall clock when no override is supplied. Immutable execution receipts are now
validated from repository-owned, hashed fields only; remote provider lookup remains outside this
local evidence check.
