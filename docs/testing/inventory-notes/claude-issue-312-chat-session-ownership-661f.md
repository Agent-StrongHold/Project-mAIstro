---
inventory-delta:
  packages/hive-conductor/backend/tests: +24
  tests/: +17
---
# claude-issue-312-chat-session-ownership-661f

All 41 are new tests for #312. Nothing was removed, renamed, or moved between
suites, and `test_chat_routes.py`'s existing 15 are untouched and still pass —
a single user's experience of chat is unchanged by this fix, which is the first
thing worth knowing about it.

## packages/hive-conductor/backend/tests: +24

`tests/test_chat_session_ownership.py` is new. The route tests could not show
this defect before, because a bug about *whose* data a handler returns is
invisible until two people's data is in the store, so twenty of these run two
users: `alice` is the conftest `testuser`, `bob` is a second ordinary account
the module creates (the only other seeded account is the admin, and the admin
is refused the whole `/v1/chat/` surface — one test pins exactly that).

They cover list, get, append and delete across the boundary; that a foreign id
and a missing id answer identically in status *and* body on get, append and
delete alike; that a `user_id` in the request body is not believed; that an
unowned legacy row is in nobody's list, readable by nobody, and still on disk
afterwards; that the Welcome seed is per user and not re-seeded; and that the
revived `setup_checklist` item counts a chat you wrote and not one you were
handed.

Three mutants confirm they bite rather than merely pass: `owns()` returning
`True` fails 11 of the 20, a 403 in place of the shared 404 fails 5, and
dropping the ownership stamp on create fails 4.

The last four came from the diff-coverage report rather than the plan:
`owner_of`'s three refusals and `seed_chat_for("")` had never run, because
`AuthMiddleware` rejects an unauthenticated `/v1/` request before any handler
does. One of the three would have been silent — an empty id compares equal to
the `user_id` every legacy row carries, so admitting it would hand the
quarantined rows to whoever arrived without one.

## tests/: +17

`tests/test_check_owned_store_access.py` covers the new gate. Eleven are about
what it can and cannot see: a substring search for the store name would flag
the gate's own docstring, and the first false positive is what teaches people
to reach for `ALLOWED` instead of a fix, so the AST walk is asserted against
comments, strings and the same attribute on a different object. One asserts
that passing the raw store *into* `OwnedStore` still counts — the construction
is where the store escapes, and that is why the binding lives in
`owned_records` rather than in each caller.

Six more, also from the coverage report, drive the reporting path against a
fabricated backend tree: a planted violation named with path and line, `main()`
failing and printing, `main()` passing a clean tree, a missing backend
directory failing rather than reporting `ok` over an empty walk, and
`__pycache__` not being walked. That path only ever runs when someone is about
to ship a leak, which is a poor moment to find out it raises.
