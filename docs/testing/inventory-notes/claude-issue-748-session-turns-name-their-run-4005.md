---
inventory-delta:
  packages/maistro-core/tests: +52
---
# claude-issue-748-session-turns-name-their-run-4005

Two new files, no removals and no renames, so the whole delta is additions
(#748).

`tests/persistence/test_session_turn_provenance.py` is +44: thirteen behaviours
parametrized over the three session backends, plus three that parametrize over
the store *types* for the lifecycle check and one PostgreSQL-only index
assertion. Parametrized over all three backends for the reason
`test_backend_conformance.py` gives -- a twin that silently drops what
PostgreSQL persists passes every test written against the twin alone -- so the
count is three times what the behaviour count suggests, deliberately. Without a
`MAISTRO_TEST_PG_DSN` the PostgreSQL parametrization skips rather than
vanishing, which is why 44 collect and 13 skip on a laptop.

Four of those 44 are a class added after CI's diff-coverage gate found the
`ensure_schema` back-fill branch uncovered: on a fresh database the columns
already exist, so the `ALTER` path that upgrades a homelab file written before
028 never ran in any test. They build a three-column `session_turns` by hand and
drive the upgrade through it -- columns added, an append against the upgraded
file recording its Run, pre-existing markers kept, and a second `ensure_schema`
taking the other side of the branch. That took the file to 100% line and branch
coverage.

`tests/agents/test_outcome_names_its_session.py` is +8: four for the outcome
naming its session in the field named for it rather than in `request_id`, four
for the ledger being charged per turn instead of per conversation.

No existing test was deleted or relaxed. `tests/persistence/test_pg_outcomes.py`
gained one line inside an already-existing pinned argument tuple -- migration
028's `session_id` binds a 29th parameter -- which does not change its count.
