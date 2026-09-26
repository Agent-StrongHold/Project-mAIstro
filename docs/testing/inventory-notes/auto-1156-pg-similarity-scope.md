---
inventory-delta:
  packages/maistro-core/tests: +5
---
# auto-1156: real-PostgreSQL legs for the similarity query's scope axes

Repair evidence for the lane's diff-coverage gate: `scripts/check-diff-coverage.py
coverage.xml --base 8bb344e3` failed at 82.8% on
`packages/maistro-core/src/maistro/persistence/pg_learnings.py` because no
covered producer ever executed the changed `team_id`/`user_id` param branches
(283-286) or the multi-axis `similarity_query` call (289) — the migrations
suite drives only the org/agent axes, and `test_pg_learnings.py` was
fake-pool-only.

Five nodes appended to the existing `PgLearningStore` suite, all real-pool
(`pg_pool` fixture, `requires_postgres`), mirroring the migrations suite's
convention of making out-of-scope rows the *better* vector match so a missing
filter flips the result set:

- `test_find_similar_scope_axes_bind_exactly_against_a_real_server` — team and
  user exact, agent keeps the shared-pool widening, org exact, unembedded row
  excluded, every branch arc out of the changed conditionals exercised;
- `test_find_similar_orders_by_cosine_distance_nearest_first` — `<=>` ranking;
- `test_find_similar_refuses_a_width_the_column_cannot_hold`;
- `test_set_embedding_refuses_a_width_the_column_cannot_hold`;
- `test_text_of_reads_the_text_that_actually_persisted`.
