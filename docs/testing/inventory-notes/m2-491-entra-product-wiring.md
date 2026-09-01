---
inventory-delta:
  packages/hive-conductor/backend/tests: +18
---
# M2 #491 Entra product wiring

Adds eighteen Hive backend pytest node IDs across three concerns:

- eight verifier-dispatch cases covering tenant extraction, rejection of
  multi-tenant aliases and non-Microsoft issuers, cross-tenant endpoint mixing,
  userinfo avoidance, generic OIDC parity, Entra `tid:oid` normalization, and
  wrong-tenant refusal;
- three additional human-auth policy cases covering local OAuth suppression,
  Entra-only provider restriction, and hybrid provider compatibility;
- seven product configuration/route cases covering the hybrid compatibility
  default, Entra-only configuration validation, password-login refusal, disabled
  OAuth state-allocation prevention, and hybrid generic-OIDC reachability.

This slice consumes the existing OAuthLoginService and canonical Hive session.
It does not add a second OAuth route, token exchange, identity-link store, or
session implementation.
