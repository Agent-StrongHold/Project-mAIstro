---
inventory-delta:
  tests/: +2
---

Repair follow-up to #1186: the credential authority audit used to accept a
reachable, classified-but-unscoped credential store because it validated only
the ledger's asserted `scope` strings. `scripts/check-credential-authority.py`
now corroborates principal scope in the implementation itself for the
owner-scoped kinds (`product_crud`, `encrypted_store`): the module must cite
the principal dimension outside docstrings, and no record operation may select
records by id without an owner/principal scope. The two new root-suite tests
pin the counterexample (a classified `SecretRepository` with id-only
get/rotate/delete fails the audit for both kinds) and the pass path (real
principal parameters, route-style body evidence, and global key-material
rotation are handled without false positives).
