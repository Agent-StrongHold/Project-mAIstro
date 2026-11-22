---
inventory-delta:
  packages/hive-conductor/backend/tests: +16
---

# Optimizer reads, decisions, and runs authorize their owning Workspace (#2469)

Sixteen ASGI cases through the real middleware stack pin the shared
target-resolution gate (`services/optimizer_scope`) across the optimizer's
five surfaces: global and per-DAG lists disclose only the caller's live
canonical membership universe (an authenticated unprivileged principal sees
nothing); a foreign actor's accept/reject answers the same non-disclosing
404 as an unknown id and writes no decision, audit entry, candidate, or
promotion; the owner's acceptance promotes the immutable candidate under the
gate-resolved tenant with the real actor named; a revoked member loses all
five surfaces while the session and elevation stay valid; a run refuses a
foreign-claimed DAG, a missing descriptor, and a foreign-tenant Project with
no execution, no Run, and no minted proposals; a forged Workspace field on a
stored proposal (or a registration contradicting the recordings) freezes the
whole DAG's optimizer surface instead of rehoming it; and a five-endpoint
mutation control proves each refusal is enforced by the gate — with the gate
bypassed at its one seam, every endpoint answers the cross-tenant request.

The per-tenant fixture chain (second principal, canonical workspaces, real
route-driven proposals) rides the same session fixtures `test_hitl_door.py`
uses; no service is stubbed except the validation gate's model execution,
which the run cases disable with `validate=false`. The existing
`test_optimizer.py` route cases were moved onto real descriptors and
workspace-claimed proposals — the gate refuses the descriptor-less bare-id
runs they previously exercised, which is the missing-registered-ownership
refusal the issue requires.
