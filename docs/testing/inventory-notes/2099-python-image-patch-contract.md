---
inventory-delta:
  tests/: +1
---
# 2099-python-image-patch-contract


PR #2099 adds one root-suite regression:
`tests/test_distribution_contract.py::test_hive_image_and_workflow_pin_the_same_python_patch`.
It checks that both Hive Python image stages and every exact live Python
assertion in the Dockerfile/security workflow agree on the patch release.
No test was removed, renamed, skipped or reparametrized; this is a net +1
addition to `tests/`.

The regression failed with the stale build-time `(3, 13, 15)` assertion and
passed after it was aligned to the pinned Python 3.13.16 image. Identity
package versions and operational seed checks remain unchanged.

Measured on the Python patch branch with
`uv run python scripts/check-suite-inventory.py --suite tests/ --update --note 2099-python-image-patch-contract`:
expected 5172 before this note, collected 5173 unique node IDs, zero duplicate
evidence. This matches CI job 114090550931 on commit
`3c96524c0ffe46ea01845ee6ead45e8126356b2f`. No baseline reset or compaction.
