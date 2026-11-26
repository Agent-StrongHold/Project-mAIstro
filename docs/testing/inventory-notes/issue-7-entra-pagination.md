---
inventory-delta:
  packages/hive-conductor/backend/tests: +17
---

# Issue #7: bound Entra membership pagination before sending credentials

Adds 14 parametrized resolver cases and three real OAuth callback cases to
`test_entra_jit_provisioning.py`. The resolver must reject foreign origins,
insecure URLs, non-default ports, userinfo, fragments, a different subject's
membership path, relative/invalid URLs, and malformed continuation values.
An eligible first page is deliberately present: partial evidence must not
create an account, link, or session. Request counts prove no second request
sends the login bearer token; audit assertions prove refusal without token
logging. Existing multi-page success and bounded-loop cases remain in place.

Regression demonstration and final validation results are recorded in
`docs/implementation/issue-7-handoff.md`. This is a bounded repair of the
salvaged #492 slice, not evidence that milestone #7 is complete.
