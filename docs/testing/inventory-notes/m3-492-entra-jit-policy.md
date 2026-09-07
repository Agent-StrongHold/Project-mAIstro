---
inventory-delta:
  packages/hive-conductor/backend/tests: +13
---
# M3 #492 Entra JIT entitlement-policy slice

Adds thirteen pytest node IDs covering disabled-by-default admission, eligible and
ineligible group decisions, deterministic multi-group composition, incomplete
claim/overage refusal, authoritative resolver evidence, entitlement revocation
on group removal, immutable group-object-ID configuration, duplicate-ID
normalization, role precedence, role/permission ceilings, and separation of
SSO-managed entitlements from local/manual grants.

This is the pure policy slice only.  It is stacked on #902/#491 and performs no
account creation, directory call, store mutation, or session issuance.
