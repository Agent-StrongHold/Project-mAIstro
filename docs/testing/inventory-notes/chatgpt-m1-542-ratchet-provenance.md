---
inventory-delta:
  tests/: +22
---
# chatgpt-m1-542-ratchet-provenance

Twenty-two root tests are added for #542.

Thirteen tests in `tests/test_check_ratchet_provenance.py` pin the inventory mechanism:
candidate-controlled ledgers fail; direct trusted resolution passes; `ROOT`, `REPO`,
and `REPO_ROOT` path aliases and direct function path expressions are discovered;
deliberate candidate-authored specifications are accepted only when explicitly
classified; delegated consumers require a real adapter using the shared resolver;
adapters may use the same stem identity as the reachability tooling graph; a
delegated adapter is actually executed and its non-zero result fails; the lightweight
`--inventory-only` mode cannot execute delegated gates; and a checker that cannot be
parsed fails the inventory closed.

One repository-level test in `tests/test_ratchet_provenance_repository.py` is the
CI proof: the live scripts/tooling tree must have no unclassified quality-ledger
consumer. Runtime execution of delegated trusted-base adapters remains in the required
Vulture Ratchet workflow, where full git history and the event's integration-base
context exist.

Eight tests in `tests/test_m1_542_review_regressions.py` answer the Codex review
findings directly: the inventory discovers quality-ledger consumers under `tools/`;
stale trusted-adapter mappings fail; the lifecycle consumer has a real trusted adapter;
GitHub pull-request, merge-group, and push metadata each resolve the correct integration
base; a clean enumeration run can reach zero debt without being mistaken for an empty
measurement; changing a public route's matching kind requires prior authorization; a
candidate mutation baseline cannot lower a trusted kill-rate floor; and an explicit
external mutation baseline remains a supported local input rather than being forced
through repository-history resolution.
