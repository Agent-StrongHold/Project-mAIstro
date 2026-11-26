---
inventory-delta:
  packages/maistro-core/tests: +5
---
# 1790 — pin the two `Principal.from_legacy_dict` narrowing behaviours

Issue #1790 re-lands the P0.1/P0.2 ratchets with five corrections. Correction 2
refactored `Principal.from_legacy_dict` instead of granting its C(14) block,
and the issue records that the refactor made two behaviours explicit which
"should stay that way":

1. a bare string (`{"roles": "admin"}`) yields the **empty set**, not the set
   of its characters — the character-split reading would silently invent four
   bogus roles;
2. a singular `role` beats a plural `roles` when a dict carries both, because
   the dict was narrowed upstream and reading the plural would widen it back.

The re-land shipped the refactor with no test covering either behaviour, so a
later "simplification" of `_frozenset_str` or `_roles_from_user` could reopen
either one with nothing failing. This change adds
`packages/maistro-core/tests/identity/test_principal_legacy_dict.py` with five
tests: one per behaviour plus its complementary control (plural used when the
singular is absent; real list/tuple/set inputs still parse; every repeated
field, not only `roles`).

Both tests were shown to fail against the exact regressions they name: a
char-splitting `_frozenset_str` fails the two bare-string tests, and a
plural-first `_roles_from_user` fails the precedence test. The ratchet suites
(`tests/test_check_principal_identity.py`,
`tests/test_check_route_permissions.py`, the provenance suite, and
`packages/maistro-core/tests/identity`) are unchanged by this note; their
counts were already banked by the #1805 re-land.
