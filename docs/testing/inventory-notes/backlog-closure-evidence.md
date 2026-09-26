---
inventory-delta:
  tests/: +20
---
# Backlog closure evidence (#101)

`tests/test_check_backlog_consistency.py` goes from 17 to 37 node IDs, all new
cases for the closure-evidence rule added to `scripts/check-backlog-consistency.py`:
an unevidenced `Implemented` item fails; PR/issue links (three forms, plus one in
the header suffix) and an existing repo path pass, including on a wrapped bullet
line; a missing path is rotted; a token outside any top-level directory and a
`..` path are not evidence; evidence does not leak across items or headings; an
`Abandoned` item needs a reason (one failing, two passing forms); and the legacy
set is tolerated, must be banked when an id gains evidence (two forms), fails
when an id reopens or disappears (two forms), and matches exactly the real
file's unevidenced terminal items. No existing test was removed or renamed.
