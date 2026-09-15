---
inventory-delta:
  tests/: +1
---
# Issue #751 compliance validator repair

Adds regression coverage for a pipe-less control row and a nonexistent GitHub Actions
execution. The latter proves that a repository-owned receipt cannot make an invented
run ID support an implemented claim; the validator must inspect the canonical run.
