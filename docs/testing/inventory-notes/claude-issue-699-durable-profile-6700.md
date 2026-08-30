---
inventory-delta:
  packages/hive-conductor/backend/tests: +70
---
# claude-issue-699-durable-profile-6700

All 41 are new, in one file: `tests/test_profile_durability.py`. Nothing was
deleted, renamed, or moved, so the +41 is the whole story of the count.

They cover the six criteria of SPEC-083026-ef62:

- **AC-1, 7 tests** — a profile read back from a second record store over the
  same rows; the same claim once more against a real `maistro.state.State` and
  its writer thread rather than a double, because the doubles cannot show that
  `flush` drains before the read-back; `durable` reported on both store kinds;
  a forward-version and an unparseable record refused rather than read as
  empty; and a `GET` that stores nothing.
- **AC-2, 8 tests** — three record-store doubles that fail in the three ways a
  real one can (accepts and forgets, refuses outright, keeps something else),
  each of which must reach the caller; the flush; a delete that left the record;
  and the two HTTP surfaces answering 503, plus the chat tool answering an
  error instead of `updated: True`.
- **AC-3, 5 tests** — that no code names the `user_profiles` table and that
  the cache and its hydrator are gone. Parsed from the AST, not grepped: this
  file and `chat_completion.py`'s explanatory comment both say those names, so
  a text scan would flag the explanation and invite an allowlist that would
  have to name the real call sites to work. Comments are not in the AST.
- **AC-4, 8 tests** — the round trip in both directions between the route and
  the chat tools, including the defect itself (a `profile_set` that used to
  erase everything the panel had saved), the model-curation path, and the
  system prompt. Two of them hold the no-cache property directly: a write made
  behind the module's back is visible on the next read, and two reads do not
  hand back the same object.
- **AC-5, 8 tests** — deletion removing the record rather than emptying it,
  one principal's delete leaving another's profile alone, two principals not
  sharing a record, the removed `"dev"` fallback now answering 401, and the
  durability flag on the route.
- **AC-6, 4 tests** — read from `KnowledgeBase.tsx`, since this suite has no
  JS runner. Deliberately narrow: that the empty `.catch(() => {})` is gone,
  that a non-OK response is treated as a failure, and that something renders
  from it. Not the wording and not the styling.

## The Codex review, +29 more

Five findings, all real, all fixed — and the diff-coverage gate was red on the
same lines, because the branches Codex named were the ones no test entered.

- **AC-2, +14** — a reader that fails the way a real one can (I/O, permissions,
  a malformed database, no descriptors) now raises `ProfilePersistenceError`
  rather than escaping unclassified, so `GET` answers the documented 503 like
  the `PUT` beside it; the schema refusals for a non-object, a non-integer
  version and a record that fails validation; a write that reads back
  unparseable; and two structural cases holding the handlers off the event loop
  (a profile write waits in `State.flush()`, so the route handlers are `def`
  and the chat tools go through `asyncio.to_thread`).
- **AC-3, +2** — `PROFILE_STORE_CUTOVER` logged when PostgREST is still
  configured, and silent when it is not.
- **AC-4, +9** — `PATCH /v1/profile`, which the panel now uses: `PUT` replaced
  the whole document, so the page's load-time snapshot deleted anything set in
  chat or a second tab since. Plus the field-name guards and the tool
  argument-validation branches the coverage gate named.
- **AC-1, +1** — the ephemeral store's own delete and listing, which every test
  and every `memory://` deployment runs on.
- **AC-6, +2 (in place)** — the panel checks `r.ok` before treating a response
  as a profile, and saves one field rather than the document.

## Mutations run

Ten, against the new tests. Nine were killed on the first pass: dropping the
read-back from `save`; `delete` writing an empty record instead of removing
it; `set_field` starting from `{}` (the original defect); `_read_back` skipping
its comparison; `write` skipping the flush; `_decode` accepting a forward
version; the `"dev"` principal fallback restored; and the route swallowing the
persistence error.

The tenth **survived**: making `preferences()` hand back the record's own dict
instead of a deep copy changed nothing, because `load()` decodes from the store
on every call and so there is no shared object to defend. The copy was dead
code and the test for it was vacuous. Both were removed, and replaced with the
two tests that hold the property that is actually load-bearing — reads go
through to the store. Re-mutated by reintroducing a process cache in `load()`:
11 of the 41 fail.


Eight more against the review fixes. Seven killed first time: `_read` no longer
wrapping store failures (3 fail); `GET` no longer catching them; `PATCH`
replacing the document instead of setting a field; a handler back to `async`;
a chat-tool write back on the loop; the cutover warning silenced; the panel
back to `PUT` of the whole profile.

The eighth **survived**: deleting the `if (!r.ok) throw` line left the test
passing, because it looked for the substring `r.ok` and the comment above the
check contains those characters. That is the same trap as the AST-versus-grep
one in AC-3, one layer down. Rewritten to assert on the branch inside the
`/v1/profile` fetch; re-mutated and killed.
