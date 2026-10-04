---
inventory-delta:
  packages/maistro-core/tests: +26
  packages/maistro-server/tests: +5
---
# Issue 1047 - durable cross-Workspace user model

Adds the #1047 follow-up layer on top of the existing `UserModelFact` types,
in-memory store and self-consented promotion: a relevance-gated recall path,
the one canonical `UserModelService` shared by the Agent runtime and the HTTP
API, a PostgreSQL system of record (migration 054) with its durable-table
retention declarations, and `/v1/user-model` owner-control routes.

New tests, all in `packages/maistro-core/tests/memory/user_model/` and
`packages/maistro-server/tests/api/`:

- `test_retrieval.py` (+11): pins the structural zero (an unrelated task can
  never receive a fact, whatever its confidence or freshness), the hard
  gates (review state, temporal expiry, owner privacy mark, sensitivity
  opt-in, confidence floor), Persona-lifted ranking, reinforcement ordering,
  and owner scoping.
- `test_cross_workspace.py` (+8): the acceptance E2E — Workspace A evidence
  surfaces in Workspace B only for relevant tasks and never for unrelated
  ones; never-promoted Workspace-private memory stays invisible; colliding
  users share one durable store without seeing each other's facts (including
  forget isolation); correction changes later retrieval and keeps lineage
  provenance; a forgotten fact cannot be recreated by a stale working-graph
  replay or by the corrected wording; Persona shapes ranking but a cross-user
  promotion is refused regardless.
- `test_pg_store.py` (+7, env-gated on `MAISTRO_TEST_PG_DSN`): the durable
  twin's protocol conformance — full field round-trip through JSONB rows,
  revision ordering, owner scoping, tombstone purge with every historical
  wording still blocked, and the restart case (a new store instance reads
  back what the previous one wrote).
- `packages/maistro-server/tests/api/test_user_model_api.py` (+5): the HTTP
  surface derives the acting user from the authenticated principal only,
  returns 404 for foreign lineages, projects correct/mark-private/forget with
  provenance, keeps recall relevance-gated per principal, and answers 503
  when no durable store is configured.
