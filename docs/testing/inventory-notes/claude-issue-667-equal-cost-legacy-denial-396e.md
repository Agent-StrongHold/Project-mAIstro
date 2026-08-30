---
inventory-delta:
  packages/maistro-core/tests: +3
---
# claude-issue-667-equal-cost-legacy-denial-396e

Three added, none removed, none rewritten, all in
`tests/security/test_passwords.py` under `TestEveryDenialCostsTheSame`.

The property is asserted as "a decoy verification was performed", not as
elapsed time. Wall-clock on a shared runner is not a stable assertion, and the
thing that matters is the work done rather than any particular duration — the
oracle in #366 was four orders of magnitude wide precisely because one path
did no work at all.

Two of the three are the cases that must spend: an unknown account (the #366
control, which was already true) and a legacy bcrypt hash in a deployment
without the extra (the regression). The third is the case that must **not**:
an account whose hash can actually be checked. Without it, a fix that spent a
decoy unconditionally would satisfy the other two while doubling the cost of
every ordinary login.

Removing the one-line spend fails exactly the regression case and leaves the
other twenty-two passing.
