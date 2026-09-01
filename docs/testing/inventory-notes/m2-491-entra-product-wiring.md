---
inventory-delta:
  packages/hive-conductor/backend/tests: +24
---
# M2 #491 Entra product wiring

Adds twenty-four Hive backend pytest node IDs across four concerns:

- eight verifier-dispatch cases covering tenant extraction, rejection of
  multi-tenant aliases and non-Microsoft issuers, cross-tenant endpoint mixing,
  userinfo avoidance, generic OIDC parity, Entra `tid:oid` normalization, and
  wrong-tenant refusal;
- three additional human-auth policy cases covering local OAuth suppression,
  Entra-only provider restriction, and hybrid provider compatibility;
- seven product configuration/route cases covering the hybrid compatibility
  default, Entra-only configuration validation, password-login refusal, disabled
  OAuth state-allocation prevention, and hybrid generic-OIDC reachability;
- six explicit account-link cases covering authenticated-only link start,
  browser state without a client-carried user id, callback re-resolution of the
  current Hive session, no second session issuance, service-level verified
  subject binding, and behavioral proof that ordinary unlinked login never
  auto-links even when a verified email is present.

This slice consumes the existing OAuthLoginService and canonical Hive session.
It does not add a second token exchange, identity-link store, or session
implementation; the only new route is the authenticated explicit-link start
surface, and it reuses the canonical OAuth callback.
