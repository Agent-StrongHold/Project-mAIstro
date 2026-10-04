---
inventory-delta:
  tests/: +30
---
# auto-400-workflow-inventory

#400 — remove the always-green stream1 diagnostic workflow and gate its rots.

`tests/test_check_workflow_inventory.py` (+30) pins `scripts/check-workflow-inventory.py`,
the new gate behind `quality/workflow-inventory.json`. The workflow file it exists
for — `.github/workflows/stream1-diagnostic.yml` — carried no tests and could have
none that failed: it was pinned to a deleted branch and swallowed every error.
The 30 cases cover the four rules that would have caught it: the inventory closes
the set in both directions, dispositions fit their actual triggers, trigger branches
and 40-hex commit pins must resolve in the checkout, and every error swallow
(`|| true`, `continue-on-error: true`) needs a written reason within six lines.
No existing suite lost or gained tests: the change deletes a workflow, adds one
script and one JSON inventory, and adds reason comments to five workflows.
