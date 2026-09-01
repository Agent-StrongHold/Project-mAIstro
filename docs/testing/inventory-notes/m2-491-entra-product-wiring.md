---
inventory-delta:
  packages/hive-conductor/backend/tests: +8
---
# M2 #491 Entra product-verifier wiring

Adds eight Hive backend pytest node IDs covering tenant extraction, rejection of
multi-tenant aliases and non-Microsoft issuers, cross-tenant endpoint mixing,
userinfo avoidance, unchanged generic OIDC dispatch, Entra `tid:oid`
normalization, and wrong-tenant refusal.

This slice injects the product-level verifier into the existing OAuthLoginService.
It does not add a second OAuth route, token exchange, identity-link store, or
session implementation.
