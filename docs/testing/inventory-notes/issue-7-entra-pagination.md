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

All 17 additions failed against the unchanged production resolver, then
passed with the repair (39 JIT tests total). The complete backend suite passed:
3983 passed, 26 skipped. The scoped inventory gate confirms 4009 collected
node IDs, matching the existing inventory plus this +17 delta. Root ruff
check/format and release, reachability, promotion-surface, backlog, radon and
contract-marker gates passed. Exact commands and milestone acceptance limits
are recorded in `docs/implementation/issue-7-handoff.md`.

This is a bounded repair of the salvaged #492 slice, not evidence that
milestone #7 is complete.
