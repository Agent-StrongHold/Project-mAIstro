---
inventory-delta:
  packages/maistro-core/tests: +44
---
# 959 — external Agent delegation bound to canonical identity and evidence

Issue #959 (M9-D2) made a cross-instance external Agent dispatch a governed
capability effect, and the tests follow the two halves of that change.

## What moved

**+21 in `tests/graph/nodes/test_agent_delegate_remote_governance.py` (new).**
One test class per acceptance criterion: no external call without a canonical
caller and Workspace scope (six refusal paths plus the positive half — the
admitted request carries the caller and scope to the peer); delegated authority
attenuated against the peer's declared scope ceiling (excess refused before any
child Run, within-ceiling narrowed onto the wire, Binding provider pinning, and
a policy denial stopping the dispatch before the transport); traceability of the
child Run's identity/Goal/Subgoal binding on both delegation paths; the dispatch
being exactly one governed Invocation on the canonical ledger — including the
UNKNOWN-after-transport-failure state that never re-POSTs blindly, the recovery
poll settling the row through the reconciliation seam, and the COMPLETED replay
after a crash between dispatch and pause; remote Agent-generated ids staying
receipts (a forged `run_id` in an answer settles nothing); and result provenance
(peer endpoint, remote Agent version) surviving into the persisted Attempt
evidence, with absent facts staying absent.

**+3 in `tests/a2a/test_delegation_context.py` (new).** The `DelegationContext`
contract itself: required canonical fields, Goal/Subgoal coherence via
`validate_goal_binding`, payload round-tripping, and the attenuation arithmetic
(order-preserving intersection, refusal-not-narrowing, empty ceiling fail-closed).

**+20 across the existing delegation/peer files.** `test_guest_peers.py` grew the
transport-boundary gate (context-less refused, envelope/context agent mismatch,
scope excess refused at the boundary, context verbatim on the POST body) and
every pre-existing delegate call now presents a canonical context, because an
unattributed external call is no longer constructible. The three pre-existing
cross-instance tests in `test_agent_delegate_remote.py`, the six child-Run
tests, and the three recovery tests in `test_agent_delegate_remote_review.py`
gained the governed wiring they now require (run store, `agent_delegation`
Binding, effect context, attempt-scoped context) — same behaviors asserted,
now through the admitted path, plus the reconciliation-park outcome a governed
transport failure produces.

## Shared fixture

`tests/graph/nodes/_delegation_governance.py` holds the one governed-node
fixture (in-memory effect context with an operator-style `agent_delegation`
Binding, a registered peer, the canonical context builder) so the three
delegation test files exercise the same composition production resolves.
