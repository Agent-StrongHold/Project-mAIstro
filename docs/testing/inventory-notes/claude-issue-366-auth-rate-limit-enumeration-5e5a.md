---
inventory-delta:
  packages/hive-conductor/backend/tests: +19
  packages/maistro-core/tests: +36
---
# claude-issue-366-auth-rate-limit-enumeration-5e5a

All 55 are new tests for #366. Nothing was removed, renamed, or moved between
suites, so the two numbers are the whole story rather than a net.

## packages/maistro-core/tests: +36

`tests/security/test_auth_throttle.py` is new (+27) and covers the limiter as
a unit: an attempt is charged to the client key, the account key and the
global counter at once; a success clears the two narrow scopes and never the
global one; the delay is progressive, capped, and the same for a known and an
unknown account; `register` and `elevate` draw on their own budgets; and the
in-process store evicts rather than growing without bound.

`tests/security/test_passwords.py` gains +9 for `equal_cost_verify`: an absent
stored hash still runs one verification against a decoy, the decoy is built
once and lazily (hashing costs ~90 ms and 64 MiB, so building it at import
would be paid by every consumer of the module), and the return value does not
say which branch ran.

## packages/hive-conductor/backend/tests: +19

`tests/test_auth_throttle_routes.py` is new. Sixteen prove the policy is
*reached* through the real endpoints — a correct policy nothing calls is the
shape #257 was filed about, and the login route had to be restructured rather
than merely have a call added, because `and` short-circuiting was the defect.
They cover login answering identically for an unknown account and a wrong
password, each of login/register/elevate exhausting only its own budget, a 409
on a taken username being charged, and the client key coming from the socket
peer unless a trusted proxy is configured.

The last three came from the diff-coverage report rather than from the plan:
restructuring `login` pulled the disabled-account branch into this change and
it had never been exercised. That branch answers 403 where everything else
answers 401, so it is only safe because it sits inside the verified branch. The
tests pin the ordering (hoisting `is_active` above the password comparison now
fails five tests instead of none) and pin that a 403 is not charged to the
throttle.
