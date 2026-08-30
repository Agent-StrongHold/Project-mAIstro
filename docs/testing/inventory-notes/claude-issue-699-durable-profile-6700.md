---
inventory-delta:
  packages/hive-conductor/backend/tests: +41
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
