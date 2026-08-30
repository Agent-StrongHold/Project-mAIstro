---
inventory-delta:
  packages/maistro-core/tests: +31
---
# claude-issue-717-unreached-invocation-and-absent-usage-f6a4

Three new files, no removals and no renames — the +31 is all addition.

- `tests/capabilities/test_invocation_layer_states_its_reach.py` (+11): the
  capability Invocation layer's statements of reach, asserted against the real
  modules rather than a transcript, plus two checks that the claims are true —
  that no `src` module calls the seam, and that no revision creates
  `capability_invocations`.
- `tests/agents/test_turn_usage_is_counted.py` (+10): a turn's token total says
  how many provider calls it summed, on both strategies. The distinguishing
  case is a provider that returns no `usage` object at all, which is why these
  script the client rather than using `FauxProvider` — that always emits one.
- `tests/persistence/test_outcome_usage_count.py` (+10): `usage_reported_calls`
  round-trips on SQLite and on a real migrated PostgreSQL, and `None` stays
  `None` rather than becoming a measured `0`.

One existing test changed rather than being added: `test_pg_outcomes.py`'s
pinned argument tuple gained the new column's `None`.
