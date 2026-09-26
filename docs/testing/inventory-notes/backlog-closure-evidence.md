---
inventory-delta:
  tests/: +28
---
# Backlog closure evidence (#101)

`tests/test_check_backlog_consistency.py` goes from 17 to 45 node IDs, all new
cases for the closure-evidence rule added to `scripts/check-backlog-consistency.py`:
an unevidenced `Implemented` item fails; PR/issue links (three forms, plus one in
the header suffix) and an existing repo path pass, including on a wrapped bullet
line, and a `.github/` file passes; a missing path is rotted; a token outside
any top-level directory, a `..` path, a directory and a file under `.git`,
`.venv` or `__pycache__` are not evidence (four cases); a bullet after a `---`
rule, or after a malformed item header, does not attach to the item above; evidence does not leak across items or headings; an
`Abandoned` item needs a reason (one failing, two passing forms); and the legacy
set is tolerated, must be banked when an id gains evidence, fails when an id
is re-closed under the other terminal status (two directions) or reopens or
disappears (two forms), and matches exactly the real
file's unevidenced terminal items. No existing test was removed or renamed.
