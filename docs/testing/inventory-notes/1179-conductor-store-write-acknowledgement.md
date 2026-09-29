---
inventory-delta:
  packages/hive-conductor/backend/tests: +5
---
# 1179-conductor-store-write-acknowledgement

## What changed

#1238 made `PersistedStore.put/delete/put_raw` acknowledged writes
(`State.submit_sync`), but three Conductor record stores still wired durability
by hand: `PersistedSettingsRecordStore`, `PersistedProfileRecordStore`, and
`PersistedRegistrationRecordStore` each took an injected `state.flush` callable
and drained the whole writer queue after every write. That is the pattern #1179
forbids — the durability contract depended on each store remembering to call
`flush`, and `flush` surfaces no errors, so the acknowledgement that mattered
was the one inside `put_raw`, not the drain.

- `services/settings_store.py`, `services/profile_store.py`,
  `services/registration_policy.py`: the `flush`/`timeout` constructor
  parameters are gone. `write`/`remove` rely on the acknowledged
  `put_raw`/`delete` — return only after the State commit, raise the writer's
  failure. Docstrings state the contract (#333/#1179).
- `services/foundation.py`: wiring updated; the comment now names the
  acknowledgement rule instead of the queue drain.
- `stores.py`: new public `persistence_backend()` accessor.
- `routes/health.py`: `/health` reports a `persistence` block — per-family
  durability/ack mode (`durable-ack`/`ephemeral`/`memory`, `unknown` when
  unreadable) — and `docs/architecture/CONDUCTOR-PERSISTENCE-MAP.md` is the
  store-by-store map (#1135 visibility half).
- Stale comments that said a profile write "waits in `State.flush()`"
  (`routes/profile.py`, `services/chat_completion.py`) now describe the
  acknowledged write.

## Tests

- `packages/hive-conductor/backend/tests/test_state_commit_acknowledgement.py`
  (+5), against a real writer thread and SQLite file: the settings `PUT` has no
  response while the write sits queued behind a stalled writer transaction and
  the row is not on disk; after the 2xx a fresh `State` over the same file
  (crash probe) holds the acknowledged mutation; a failing commit answers 5xx
  without echoing the refused value, which is absent after restart while the
  prior record is intact; `ModelStore.__setitem__` against a failing commit
  raises with memory still coherent with disk; `/health` names the mode for a
  configured and for an all-memory deployment.
- `test_profile_durability.py`: the flush-pinning test is replaced by
  `test_a_write_is_committed_when_put_raw_returns` (fresh-reader proof, no
  flush); doubles updated to the acknowledged-write shape.
- `test_settings_durability.py`, `test_registration_policy.py`: constructions
  updated to the flush-free record stores; restart cases unchanged and green.
