---
inventory-delta:
  packages/hive-conductor/backend/tests: +41
---
# claude-issue-334-durable-conductor-settings-d982

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

`tests/test_settings_durability.py` — 41 tests for SPEC-082926-0b72 (#334).

Thirty-one distinct test functions; one is parametrised over three credential
detectors (`access_token=`, `sk-`, a connection string), which is why the node
count exceeds the function count.

Nine of the thirty-three exist because the diff-coverage gate found real gaps
rather than because an acceptance criterion asked for them: `_fetch_available_models`
and `_default_model_picked` both read the record now and neither had a test,
and `apply_default_settings_if_needed` gained a write path — including the one
where the repair does not land and startup has to carry on without claiming it
did.

Nothing was removed or renamed. Two existing assertions moved from
`stores.settings` to `settings_store.current()` in `test_capabilities_settings.py`
and `test_capabilities_routes.py` — same tests, same claims, reading the record
instead of a module attribute that no longer exists.

The split is deliberate: nineteen drive `services.settings_store` with an
injected record store, because the interesting failures (a write that does not
land, a record from a future build, a document written before the envelope) are
ones a real store will not produce on demand. The restart case runs against a
real `maistro.state.State` on a real SQLite file, closed and reopened, because
against a fake it would prove nothing.


Codex's review added seven more, covering every finding it raised that this branch then
fixed: the revision check and the write observed as one critical section (and
again from the outside, with a store slow enough to interleave without it); a
store whose `write` raises translated into a `SettingsPersistenceError` and a
503 rather than an unclassified 500; and a structural assertion that Setup's
durable write is not inside a broad `except Exception` — structural because the
defect was the handler, not the call, and `/v1/setup/complete` refuses once
provisioning has run, so a test that un-provisions the app would be testing the
fixture.
