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
adapters may use the same stem identity as the reachability tooling graph; a
delegated adapter is actually executed and its non-zero result fails; the lightweight
`--inventory-only` mode cannot execute delegated gates; and a checker that cannot be
parsed fails the inventory closed.

One repository-level test in `tests/test_ratchet_provenance_repository.py` is the
CI proof: the live scripts tree must have no unclassified quality-ledger consumer,
and every live delegated trusted-base adapter must execute successfully. That is
the test that prevents a future ratchet from quietly reintroducing the
candidate-is-its-own-oracle defect.
