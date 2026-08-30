---
inventory-delta:
  tests/: +14
---
# chatgpt-m1-542-ratchet-provenance

Fourteen root tests are added for #542.

Thirteen tests in `tests/test_check_ratchet_provenance.py` pin the inventory mechanism:
candidate-controlled ledgers fail; direct trusted resolution passes; `ROOT`, `REPO`,
and `REPO_ROOT` path aliases and direct function path expressions are discovered;
deliberate candidate-authored specifications are accepted only when explicitly
classified; delegated consumers require a real adapter using the shared resolver;
adapters may use the same stem identity as the reachability tooling graph; delegated
execution propagates a non-zero result; `--inventory-only` remains structural; and a
checker that cannot be parsed fails the inventory closed.

One repository-level test in `tests/test_ratchet_provenance_repository.py` proves the
live scripts tree has no unclassified quality-ledger consumer. Runtime execution of
every live delegated trusted-base adapter belongs to the required Vulture Ratchet
workflow, which supplies full git history and the event-bound integration base; the
generic root pytest job intentionally stays structural rather than duplicating those
environment-dependent ratchets in a depth-1 checkout.
