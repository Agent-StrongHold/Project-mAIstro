---
inventory-delta:
  tests/: +5
  packages/hive-conductor/backend/tests/: credential-store isolation fixture
---

#1186 retires the unscoped `credential_store_v2` implementation and adds
root-suite checks for the credential authority ledger: the retired path stays
deleted and no second production credential-store implementation appears.
The existing per-user `UserCredentialStore` and runtime `CredentialRouter`
remain the only canonical owners. Backend credential route tests now receive a
fresh encrypted store per test, preventing a prior test's admin credential from
masking the two-user isolation assertion.
