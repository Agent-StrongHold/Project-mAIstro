---
inventory-delta:
  packages/maistro-core/tests: +48
---
# claude-issue-748-session-turns-name-their-run-4005

Two new files, no removals and no renames, so the whole delta is additions
(#748).

`tests/persistence/test_session_turn_provenance.py` is +40: thirteen behaviours
parametrized over the three session backends, plus three that parametrize over
the store *types* for the lifecycle check and one PostgreSQL-only index
assertion. Parametrized over all three backends for the reason
`test_backend_conformance.py` gives -- a twin that silently drops what
PostgreSQL persists passes every test written against the twin alone -- so the
count is three times what the behaviour count suggests, deliberately. Without a
`MAISTRO_TEST_PG_DSN` the PostgreSQL parametrization skips rather than
vanishing, which is why 40 collect and 12 skip on a laptop.

`tests/agents/test_outcome_names_its_session.py` is +8: four for the outcome
naming its session in the field named for it rather than in `request_id`, four
for the ledger being charged per turn instead of per conversation.

No existing test was deleted or relaxed. `tests/persistence/test_pg_outcomes.py`
gained one line inside an already-existing pinned argument tuple -- migration
028's `session_id` binds a 29th parameter -- which does not change its count.
