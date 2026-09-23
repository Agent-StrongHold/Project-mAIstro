---
inventory-delta:
  packages/hive-conductor/backend/tests: +11
  packages/maistro-core/tests: +9
---
# aud12-registration-coverage

Diff-coverage floor tests for #1248's username-registration concurrency fix
(`_REGISTRATION_LOCK`, `ModelStore.put_if_unique`, `PersistedStore.put_model_unique`/
`put_model_if_unique`):

- `packages/maistro-core/tests`: `+9` — `TestPutModelUnique`/`TestPutModelIfUnique`
  added to `state/test_persisted_store.py`, covering the new-claim happy path,
  same-key re-save, cross-key collision (single and multi-field), and the
  transactional-rollback error paths against a real SQLite-backed `State`.
- `packages/hive-conductor/backend/tests`: `+11` — one new test in
  `test_registration_policy.py` (durable claim lost after the in-memory check
  passes) plus ~14 new cases against `ModelStore.__setitem__`/`put_if_unique`
  in `test_model_store_svc.py`, minus a couple of pre-existing parametrized
  cases folded into the new fakes, netting `+11`.
