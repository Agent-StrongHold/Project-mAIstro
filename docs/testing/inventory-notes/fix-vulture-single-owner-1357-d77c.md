---
inventory-delta:
  tests/: +27
---

# fix-vulture-single-owner-1357-d77c

Adds 27 root-suite tests covering workflow-level `paths:` filter translation
and producer untriggerability in `scripts/check-gates-ran.py` and
`scripts/check-required-checks.py` (#2059).
