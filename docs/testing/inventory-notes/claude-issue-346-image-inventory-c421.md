---
inventory-delta:
  tests/: +24
---
# claude-issue-346-image-inventory

Twenty-four added tests, no removals, nothing renamed or moved.

`tests/test_check_image_inventory.py` covers the new gate
`scripts/check-image-inventory.py` (#346). All but one run it against a
synthetic tree — which proves the logic and proves nothing about the
repository — and `test_the_real_inventory_matches_the_real_repository`
runs it against this repository. Both matter, and they fail for different
reasons: the synthetic cases when the gate's logic breaks, the real one
when someone adds a Dockerfile.

Twelve were the first pass. Twelve more came from Codex's review and the
diff-coverage floor, and are the gate's own edges rather than its happy
path: a directory named `Dockerfile.d`, a vendored `node_modules`
Dockerfile, a malformed job reference, a workflow that does not exist, a
missing inventory file, a workflow with no `jobs:` block, an entry with
no `dockerfile` key, and the same Dockerfile listed twice.

Three encode decisions rather than mechanics:

- a shipped image may lack build/scan jobs only behind a
  `coverage_exception` naming an owner, an issue and a reason (#346 AC-4)
- an exception missing any of those three is refused — an exception
  nobody owns is an exemption
- a PUBLISHED entry must state `published_digest_verified`, because
  whether the release publishes the digest that was scanned is the one
  thing job names cannot show

No production code changed. `scripts/`, `.github/workflows/`,
`quality/image-inventory.json` and `Dockerfile.research` are the other
paths touched.
