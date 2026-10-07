---
inventory-delta:
  packages/hive-conductor/backend/tests: +4
  packages/maistro-core/tests: +2
---
# Issue 1058 - HITL Workspace authorization

Adds end-to-end and core regression cases proving a principal with
`dags.write` can settle an expired pause only in a canonical Workspace where
the principal is a member; a foreign Workspace remains paused. The tests also
pin the membership predicate, effective-principal evidence, and late answer /
cancel behavior after a competing timeout settlement.

## Repair wave 5 — pending-list disclosure recheck

The audit finding against `routes/hitl.py` `/pending` remained reachable: the
route snapshotted the caller's canonical Workspace ids and then disclosed
paused payloads with no per-record live membership recheck and no shared
revocation lock, so a membership revoked after the snapshot still received the
now-foreign payload. Settlement already revalidated under the mutation lock
and `list_hitl_due` revalidated per candidate; the listing was the one door
left trusting the snapshot.

The route now builds the same discovery-mode `HitlAuthorization` the expiry
path uses and revalidates every item-carrying record against live canonical
membership immediately before disclosure (`authorization.permits`, no evidence
consumption). Machine-only pauses disclose nothing and are not rechecked, so
the added cost is one membership read per disclosed record.

`test_pending_rechecks_membership_before_disclosing_payload` pins it: with the
route's `is_member` answering revoked after the snapshot, the revoked Run's
payload is withheld and the recheck is proven to have run. Removing the
recheck fails the test (verified by mutation on this lane).
