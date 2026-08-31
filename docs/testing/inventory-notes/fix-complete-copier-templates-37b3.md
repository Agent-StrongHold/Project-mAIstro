---
inventory-delta:
  packages/maistro-bootstrap/tests: +6
  tests/: +8
---
# fix-complete-copier-templates-37b3

Copier template round-trip tests under `tests/templates/` (+8) and bootstrap
plan/resolver coverage for the new product templates (+5). One additional CLI
test in `packages/maistro-bootstrap/tests/test_cli.py` covers the human-plan
copier banner line added in `cli.py`.
