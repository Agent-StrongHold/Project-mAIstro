---
inventory-delta:
  packages/hive-conductor/backend/tests: +1
---
# auto-292-b2ab

The +1 is `test_unknown_session_refusal_is_audited` in
`packages/hive-conductor/backend/tests/test_cli_contract.py`, added by this
branch's commit `0bfc7f6c8` ("audit the unknown-session refusal in POST
/cli/exec"). It pins the audit half of the #292 contract: a session id that
no longer resolves must still produce a `cli_exec` audit row (outcome
`unknown_session`, severity `warning`, acting principal recorded) before the
404 is raised — previously that refusal path returned before any audited
branch, so the frontend's deliberate recovery retry could leave the refusal
unaudited. This salvage round additionally adds one Playwright e2e case to
`packages/hive-conductor/tests/e2e/cli-page.spec.ts` ("a failed recovery from
a vanished session renders the fresh failure") pinning the CLI.tsx
retry-failure rendering fix; it is not pytest-collected, so it does not move
this inventory (the `packages/hive-conductor/tests/e2e` entry counts only the
suite's Python tests). No test was removed and no other suite moved.

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->
