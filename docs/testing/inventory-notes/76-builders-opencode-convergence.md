---
inventory-delta:
    packages/maistro-core/tests: 15
    packages/maistro-bootstrap/tests: 5
    packages/maistro-rsi/tests: 1
---

# Issue 76 inventory delta — builders/opencode convergence onto the selector

Completes the #76 cutover for the two consumers the previous round left on
direct sandboxes, with tests pinned to the new contract:

* `packages/maistro-core/tests/sandbox/test_launcher_vm_backend.py` (+11): the
  SPEC-205 launcher seam as a vm-tier backend *behind* the canonical selector —
  tier-mismatch refusal, `UNTRUSTED_CODE` admission, scoped/host egress refused
  for the deny-only substrate, policy (not substrate config) deciding network,
  verbatim command passthrough with the dangerous-command screen, workspace
  file ops and escape refusal, idempotent destroy.
* `test_opencode_harness.py` (+1 net): the factory now boots through the
  selector; added the refuse-when-policy-exceeds-substrate case.
* `packages/maistro-bootstrap/tests/test_container_sandbox.py` (+7 net, 5 → 12):
  stub-backed selector-authority, credential-boundary (seed denylist, `.git`
  sync filter), isolation-until-sync, path-escape, exec-bridging and teardown
  contract tests, plus a Kata-gated live lane for the supported deployment
  profile.
* `test_container_sandbox_hardening.py` (−2 net, 6 → 4): the Docker create-time
  argv assertions moved to the canonical backend suites; what remains pins the
  adapter side — no container CLI is ever constructed, seed/sync tar filters.
* `packages/maistro-core/tests/sandbox/test_single_authority.py` (+3): the
  #76 convergence tripwire — no product code constructs a sandbox
  implementation directly, imports the retired Docker sandbox, or builds a
  `docker run` argv outside the canonical backends.
* `packages/maistro-rsi/tests/test_contained_validation.py` (+1): a selector
  refusal (`NoSuitableBackendError`) is `ContainmentUnavailable`, never a
  candidate verdict.
