---
inventory-delta:
  tests/: +9
---
# chatgpt-branch-independence-contract

Nine tests add the branch-independence contract without changing an existing test
suite's ownership. Eight focused tests in `tests/test_branch_independence.py`
exercise classification coverage, overlap rejection, representation validation,
exact-path legacy freezing, trusted-base anti-expansion, and the folded-note
pattern. One repository test in `tests/test_branch_independence_repository.py`
proves every current `quality/**/*.json` state file is classified exactly once.

The contract is intentionally wired through the already-required root test suite
instead of adding another workflow job. This tranche inventories and freezes the
current collaboration-state surface only; it does not migrate the ratchets that
PR #658 is changing.
