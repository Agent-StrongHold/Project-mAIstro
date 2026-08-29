---
inventory-delta:
  tests/: +12
---
# claude-issue-346-image-inventory

Twelve added tests, no removals, nothing renamed or moved.

`tests/test_check_image_inventory.py` covers the new gate
`scripts/check-image-inventory.py` (#346). Eleven run the gate against a
synthetic tree — which proves the logic and proves nothing about the
repository — and the twelfth,
`test_the_real_inventory_matches_the_real_repository`, runs it against this
repository. Both matter: the synthetic cases are what fail when the gate's
logic breaks, and the real one is what fails when someone adds a Dockerfile.

The cases worth naming: a Dockerfile with no entry fails (the failure #346
is about — `Dockerfile.research` existed and was unscanned), an entry with
no Dockerfile fails, and a shipped entry naming a job that does not exist
fails. That last one is what makes the inventory more than a document.

No production code changed. `scripts/` and `.github/workflows/` are the
only other paths touched.
