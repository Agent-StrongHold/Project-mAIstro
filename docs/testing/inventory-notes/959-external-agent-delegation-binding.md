---
inventory-delta:
  packages/maistro-core/tests: +51
  packages/maistro-server/tests: +1
---
# 959 — external Agent delegation bound to canonical identity and evidence

Issue #959 (M9-D2) made a cross-instance external Agent dispatch a governed
capability effect, and the tests follow the two halves of that change.

## What moved

**+22 in `tests/graph/nodes/test_agent_delegate_remote_governance.py` (new).**
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
evidence, with absent facts staying absent. An inactive peer is refused
before admission, so a dead registration files no execution either. A
manageable REQUIRE_APPROVAL decision parks the dispatch on the durable human
approval pause (and a decision no store can manage fails the node instead),
proving the governed seam's own pause translation is never swapped for a
reconciliation park.

**+3 in `tests/a2a/test_delegation_context.py` (new).** The `DelegationContext`
contract itself: required canonical fields, Goal/Subgoal coherence via
`validate_goal_binding`, payload round-tripping, and the attenuation arithmetic
(order-preserving intersection, refusal-not-narrowing, empty ceiling fail-closed).

**+2 in `tests/a2a/test_guest_peers.py` (identity/key binding follow-up).** One
canonical effect identity now reaches the receiver two ways that cannot
diverge: an unsupplied transport key is derived from the context's
`delegation_key` (asserted equal on the wire header and the POST body), and a
caller-supplied key that differs from the context is refused before any bytes
with the refusal audited.

**+2 in `tests/graph/nodes/test_agent_delegate_remote_governance.py`
(refusal-cleanup follow-up).** A pre-transport refusal this instance owns
(provider-pinning `CapabilityUnavailable`, policy `InvocationDenied`) releases
the reserved child Run — it must not survive as canonical evidence implying
remote work — and a retry after the operator repairs the binding claims a
fresh transport attempt and dispatches, instead of reconciling a dispatch that
provably never started (the once-only `transport_attempted` claim would
otherwise park every retry until the delegation timeout).

**+1 in `tests/graph/nodes/test_agent_delegate_remote.py` (crash-replay
follow-up).** A dispatch Invocation that landed COMPLETED as a peer decline and
crashed before settlement replays through settlement on the retry — the retry
returns the recorded rejection and files no child Run — instead of polling for
a receipt the declined dispatch can never have (the old `_completed_dispatch`
filter dropped receipt-less COMPLETED rows, sending the retry to recovery).

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

**+1 in `packages/maistro-server/tests/api/test_a2a_api.py`.** The inbound
admission files a well-formed delegation context as provenance evidence while
the admitted Run stays in the receiving Workspace's own scope, and an
unparseable binding is a 422 protocol violation rather than silently admissible.

## Shared fixture

`tests/graph/nodes/_delegation_governance.py` holds the one governed-node
fixture (in-memory effect context with an operator-style `agent_delegation`
Binding, a registered peer, the canonical context builder) so the three
delegation test files exercise the same composition production resolves.
