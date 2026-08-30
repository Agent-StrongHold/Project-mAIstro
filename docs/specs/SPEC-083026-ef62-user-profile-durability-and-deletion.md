---
id: SPEC-083026-ef62
title: A user profile is durable, deletable, and has exactly one owner
repo: maistro-engine
kind: spec
status: AC Defined
created: 2026-08-30
accepted: 2026-08-30
history:
  - status: Proposed
    date: 2026-08-30
  - status: Accepted
    date: 2026-08-30
  - status: AC Defined
    date: 2026-08-30
substrate:
  - maistro-engine#ADR-083026-3d92
implements:
  - maistro-engine#ADR-083026-3d92
related: []
supersedes: []
superseded-by: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/hive-conductor/backend/tests/test_profile_durability.py
source:
  - packages/hive-conductor/backend/services/profile_store.py
  - packages/hive-conductor/backend/routes/profile.py
  - packages/hive-conductor/backend/services/chat_completion.py
ac-modules:
  AC-1: '@flat/hive-conductor/services.profile_store'
  AC-2: '@flat/hive-conductor/services.profile_store'
  AC-3: '@flat/hive-conductor/services.chat_completion'
  AC-4: '@flat/hive-conductor/services.chat_completion'
  AC-5: '@flat/hive-conductor/routes.profile'
layer: Identity
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-083026-ef62: A user profile is durable, deletable, and has exactly one owner

## Context

`PUT /v1/profile` wrote `services.chat_completion._PROFILE_CACHE`, a module
global, then mirrored to a PostgREST table inside `contextlib.suppress`, then
returned the preferences it had been handed. The chat tools read that PostgREST
table and never the cache. No `user_profiles` table exists in this repository,
and PostgREST is unconfigured in every tracked Compose profile, so the tools
read `{}` and `profile_set` wrote `{}` plus one field back — erasing whatever
the panel had saved.

ADR-083026-3d92 records the decisions. This spec states what has to be true.

## Decision

`services/profile_store.py` owns the record, over `PersistedStore` under the
namespace `user_profiles`. Everything that reads or writes a profile goes
through it: the three HTTP handlers and the five chat-tool paths. A write is
acknowledged only after the store is read back and agrees.

Three rules carry most of the weight and are not obvious from the code:

**Reads go through to the store, always.** There is no cache. The module global
this replaces is what let the panel and the tools hold different answers, and a
cache is also what makes a second replica serve a profile its owner has already
changed. A profile read is one row.

**Read-back, not write-and-return.** `PersistedStore.put_raw` enqueues onto
`State`'s writer thread, whose loop swallows the exceptions its closures raise.
Acknowledging after `put_raw` acknowledges an unlanded write. `save` flushes,
re-reads, compares, and raises `ProfilePersistenceError` when the store does not
hold what was sent.

**Deleting a profile deletes the record.** Not "save `{}`". A profile is
user-authored, user-identifying content; leaving an empty envelope behind
would make "I deleted my profile" and "my profile is empty" the same stored
state, and the first is a deletion request the system has to be able to honour.

## Retention and scope

A profile is retained until its owner deletes it. There is no expiry: the
content is what the user said about themselves for the assistant to use, and
any schedule the system chose would silently discard something the user still
wanted. `DELETE /v1/profile` is therefore the only removal path, and it is
always available.

A profile is addressed by the authenticated principal on the request, with no
fallback identity. `/v1/profile` is not in the auth middleware's public sets,
so an unauthenticated request is already 401; the removed `"dev"` fallback
covered the remaining case, a principal carrying neither id nor username, which
would have pointed several such callers at one shared record.

## Consequences

### Positive
- The panel and the chat tools read and write the same profile.
- A failed persist is a 503, not a 200 over a discarded write.

### Negative / Trade-offs
- A write waits on the state writer queue. The previous write did not wait
  because it did not persist.

### Neutral
- Without a state database, profiles stay in-process and the record reports
  `durable: false`.

## Acceptance Criteria

AC-6 is the panel's behaviour, and it is proven: four tests in
`test_profile_durability.py` read `KnowledgeBase.tsx` and fail if the empty
`.catch(() => {})` returns, if a non-OK response stops counting as a failure,
or if nothing renders from one. What it cannot have is an `ac-modules` anchor.
The `reachable` rung requires a module the reachability graph can get to, and
that graph is over Python modules; it has no name for a `.tsx` file, so any
anchor here would either dangle (#631) or point at an unrelated module to
satisfy the rung. Declared rather than faked, with the evidence named:

<!-- ac-state: unproven AC-6 - proven by four tests in
     packages/hive-conductor/backend/tests/test_profile_durability.py; the
     `reachable` rung needs a module the Python reachability graph knows and
     this criterion is about a .tsx file, which that graph cannot name -->

```gherkin
Feature: A user profile is durable, deletable, and has exactly one owner

  @AC-1
  Scenario: A profile outlives the process that wrote it
    Given a profile saved against a records store
    When a new store is built on the same records
    Then the saved preferences are readable
    And a store built without records reports itself as not durable instead

  @AC-2
  Scenario: A write that did not land is not acknowledged
    Given a records store that accepts a write and does not keep it
    When a profile is saved
    Then the caller is told the write failed
    And the HTTP surface answers with a storage error rather than the payload
    And a store that cannot be read fails the same way rather than as a crash
    And no handler waits for the writer thread on the event loop

  @AC-3
  Scenario: No profile path reaches the absent PostgREST table
    Given the Conductor backend source
    When it is searched for the user_profiles table and the profile cache
    Then neither appears on any profile read or write path
    And a deployment still configuring PostgREST is told so at startup

  @AC-4
  Scenario: The route and the chat tools reach the same owner
    Given a profile written through the HTTP route
    When a chat tool reads the profile, sets a field, and reads it again
    Then the tool sees what the route wrote
    And the route sees what the tool set
    And the field the tool deleted is gone from both
    And a caller holding one fact can set that field alone
    And a call missing its field or value is answered, not written

  @AC-5
  Scenario: A profile is deletable, and belongs to its principal
    Given a stored profile for an authenticated principal
    When that principal deletes it
    Then the record is removed rather than emptied
    And a request carrying no usable principal is refused, not given a shared one

  @AC-6
  Scenario: The panel reports a save it could not make
    Given the identity panel saving a prompt
    When the request fails
    Then the failure is shown to the user rather than discarded
    And it saves the one field it edited rather than the whole document
    And a profile it could not load is reported, not shown as an empty one
```
