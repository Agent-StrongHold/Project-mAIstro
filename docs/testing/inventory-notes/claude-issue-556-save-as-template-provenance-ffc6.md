---
inventory-delta:
  packages/maistro-core/tests: +1
---
# claude-issue-556-save-as-template-provenance-ffc6

One added test, no removals, nothing renamed or moved.

`test_saved_from_stays_out_of_the_content_hash` in
`packages/maistro-core/tests/test_graph_definitions.py` asserts the
load-bearing half of ADR-082926-d0dc: two `NodeTemplate`s saved from two
*different* Nodes carrying identical content must share a `content_hash`.
It exists as its own test rather than as another assertion on the AC-6 test
because it is a claim about AC-7 (idempotent re-registration is a no-op),
not about AC-6 — if `saved_from` entered the hash, the store would start
refusing identical content as a redefinition conflict, and the AC-6 test
would still pass while the store broke.

The AC-6 test in the same file grew assertions but not a node ID; it was
already marked and collected.
