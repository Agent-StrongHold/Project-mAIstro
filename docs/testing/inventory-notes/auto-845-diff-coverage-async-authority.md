---
inventory-delta:
  packages/maistro-core/tests: +7
---
# #845 CI-repair: the durable (async) delegation-authority seam is measured

The merge-queue evaluation failed exactly one gate — the Coverage gate — and
its diff-coverage leg named three files whose changed lines/arcs no coverage
producer reached: `a2a/broker.py` (the `await` narrowing of an async
delegation decision), `security/sentinel/policy.py` (the same narrowing in
`Sentinel.authorize_delegation`), and
`security/sentinel/delegation_durable.py` (the durable authority's degenerate
denials, its expiry re-check, and the naive-expiry row normalization). Every
pytest producer had passed; the tests that exercised the shipped durable
authority called `await authority.authorize(...)` directly, so the
production call sites — broker and Sentinel, the only two consumers — never
executed the async branch in any measured run.

Seven core tests close the gap by driving the shipped
`DurableDelegationAuthority` (SQLite twin of the PostgreSQL store) through the
production seams, plus the authority's own fail-closed paths:

- The A2A broker delegates through the durable async authority and carries
  the host grant's effective action subset, `grant_ref` and `granted_by` on
  the delegated task metadata; a durable refusal still refuses the hop with
  the host's reason (2 tests, `tests/a2a/test_broker.py`).
- `Sentinel.authorize_delegation` awaits a durable decision and surfaces its
  provenance (1 test, `tests/security/test_delegation_authority.py`).
- The durable authority itself refuses a non-agent principal, refuses an
  owner mismatch, re-checks expiry after the store read (a store whose TTL
  filter handed back a stale row cannot authorize; a valid row behind it
  still answers), and the SQLite store reads a naive stored expiry back as
  UTC so the TTL comparison never mixes naive and aware datetimes (4 tests,
  `tests/security/test_delegation_durable.py`).

These are behavior pins, not coverage appeasement: each names a contract the
issue requires (host-authorized scope only; expiry and provenance bound to
the decision; the async seam reachable end-to-end). Reproduced locally with
CI's exact gate invocation:
`check-diff-coverage.py coverage.xml --base 774ae42f…` exits 0 (6 measured
files, all ≥90% lines / ≥80% branch arcs) and the publish-set floor holds.
