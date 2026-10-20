"""Generalized protocol conformance suites (#892, M8-A12 prototype).

One behavior-level contract per store protocol, run unchanged against every
production implementation of that protocol — the archive tier's
``tests/archive/test_archive_conformance.py`` pattern, generalized:

- ``_invocation_contract.py`` — the capability ``InvocationStore`` /
  ``EffectClaimStore`` contract (:mod:`maistro.capabilities.invocation`),
  checked against the three implementations the container wires
  (``InMemoryInvocationStore``, ``SqliteInvocationStore``,
  ``PgInvocationStore``).
- ``_approval_contract.py`` — the durable ``ApprovalStore`` contract
  (:mod:`maistro.capabilities.approval_store`), checked against its three
  implementations.

The contract modules are implementation-agnostic: a check receives a store
and a :class:`ConformanceLeg` and knows nothing about which backend it is
talking to. Backend knowledge lives in ``_legs.py`` (how to build, restart,
and close each leg) and in the xfail matrix in the test modules, where every
known cross-implementation divergence is recorded with its finding number in
``docs/testing/conformance-suite-evidence.md``.
"""
