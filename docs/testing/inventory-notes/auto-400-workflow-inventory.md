---
inventory-delta:
  tests/: +53
---
# auto-400-workflow-inventory

#400 — remove the always-green stream1 diagnostic workflow and gate its rots.

`tests/test_check_workflow_inventory.py` (+53) pins `scripts/check-workflow-inventory.py`,
the new gate behind `quality/workflow-inventory.json`. The workflow file it exists
for — `.github/workflows/stream1-diagnostic.yml` — carried no tests and could have
none that failed: it was pinned to a deleted branch and swallowed every error.
The cases cover the four rules that would have caught it: the inventory closes
the set in both directions, dispositions fit their actual triggers, trigger branches
and 40-hex commit pins must resolve in the checkout, and every error swallow
(`|| true`, `continue-on-error: true`) needs a written reason within six lines.
The repair round added the parse/shape error paths (invalid YAML, non-mapping
documents, unreadable `on:`, missing/invalid JSON inventory, malformed entries,
duplicate dispositions, `main`'s stderr escape hatch, the `__main__` guard) so
the gate's refusals are pinned, not just its acceptances.
No existing suite lost or gained tests: the change deletes a workflow, adds one
script and one JSON inventory, and adds reason comments to five workflows.
