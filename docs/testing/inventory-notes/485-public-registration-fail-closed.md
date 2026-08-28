---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---
# 485-public-registration-fail-closed

Retroactive. `e8a9ad9` ("Fail closed on public self-registration (#482) (#485)")
added `TestSecurityHeaders::test_public_registration_is_fail_closed` to
`packages/hive-conductor/backend/tests/test_security_headers.py` and shipped no
note, so the conductor suite has been one node ID over its expected count on
`develop` ever since. Attributed here rather than absorbed into whichever branch
next happened to run the check — a delta recorded under the wrong change is a
delta nobody can trace back.

Found by collecting the suite at each conductor-touching commit on `develop`:
expected/collected went 1461/1471 at `54b49b4`, 1471/1472 at `e8a9ad9`. The +10
at `54b49b4` was the #445 note landing a commit late; the +1 that survived is
this one. Recorded as part of #497, which is about the `test` job being red on
`develop` for reasons no PR introduced.
