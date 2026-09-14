---
inventory-delta:
  tests/: +2
---

#1186 retires the unscoped `credential_store_v2` implementation and adds two
root-suite checks for the credential authority ledger: the retired path stays
deleted and no second production credential-store implementation appears.
The existing per-user `UserCredentialStore` and runtime `CredentialRouter`
remain the only canonical owners.
