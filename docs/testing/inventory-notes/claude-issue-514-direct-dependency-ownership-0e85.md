---
inventory-delta:
  packages/maistro-core/tests: +3
---
# claude-issue-514-direct-dependency-ownership-0e85

Three tests in `packages/maistro-core/tests/security/test_passwords.py`, one
class: `TestBcryptIsOptionalAndItsAbsenceIsADenial`. Nothing removed or moved.

They exist because #514 moved bcrypt's ownership from `hive-conductor`'s
pyproject — where it was declared and never imported — to `maistro-core`, whose
`security/passwords.py` is what actually imports it, as the `[bcrypt]` extra.
Making the ownership explicit also makes the *absent* case real for the first
time, and `verify_password` caught only `(ValueError, TypeError)`, so a
`ModuleNotFoundError` escaped the function and reached the login route as a 500
rather than a denial.

Two of the three pin that: a correct legacy password is denied instead of
raising, and the denial names the extra so the person locked out is not left
with a silent `False` indistinguishable from a wrong password. Both fail against
the pre-change source with the exact `ModuleNotFoundError` they describe —
checked by stashing the source, not assumed.

The third is the control: Argon2id verification, which every non-legacy account
uses, is unaffected by bcrypt's absence in both directions. It passes before and
after, which is the point — a change that broke the current algorithm would
otherwise satisfy the other two.
