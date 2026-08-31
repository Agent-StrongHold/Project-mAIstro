---
inventory-delta:
  tests/: +39
---
# chatgpt-m1-542-ratchet-provenance

Thirty-nine root tests are added for #542.

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

Two tests in `tests/test_public_routes_shallow_ci.py` pin the main-CI execution shape
that exposed the final route-gate failure: a depth-one pull-request checkout must
materialize both the synthetic event ref ancestry and the declared integration target
before trusted comparison, and a failed history fetch is a hard provenance failure
rather than permission to fall back to the candidate registry.

Fifteen tests in `tests/test_m1_542_policy_coverage.py` exercise the policy branches
introduced by the trusted-ratchet conversions without weakening the coverage gate.
They drive delegated citation, contract-marker, enumeration, lifecycle, promotion,
shell-execution, reachability, and reachability-disposition adapters through trusted,
regression, malformed-input, unavailable-measurement, and unreadable-oracle outcomes;
they also exercise the direct execution-lifecycle, model-egress, public-route, Radon,
Vulture, mutation, and shared provenance paths through success and fail-closed cases.
The required Vulture Ratchet workflow remains the integration proof against real Git
history; these root tests provide deterministic branch evidence for the policy code
itself so the per-file 90%/80% diff-coverage gate remains meaningful.
