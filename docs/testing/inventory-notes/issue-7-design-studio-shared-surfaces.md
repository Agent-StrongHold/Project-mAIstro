---
inventory-delta:
  packages/hive-conductor/backend/tests: +6
---

# Issue #7 row 18: Design Studio's work opening consumes the shared persistent surfaces

Row 18 of the frozen issue #7 acceptance matrix (#777/#773) failed on reachable
production behavior: nothing in the Design Studio product consumed the
persistent Agent's shared user-memory or Attention surfaces, and
`grep 'UserModel|recall_for_task|Attention'` over the Design Studio code
matched nothing. The repair is pure composition on the canonical seams, in
the one flow where Design Studio opens work — the brief interview:

- `services/user_model.py` (new) composes the ONE
  `maistro.memory.user_model.service.UserModelService` — the same service
  `maistro_server.main` wires — over the deployment's PostgreSQL session
  factory (the same factory the design services resolve). It exposes
  relevance-gated recall only; there is no write surface and no in-memory
  lookalike: without the configured PostgreSQL the resolver answers `None`
  and callers degrade by recalling nothing (the durable user model is
  PostgreSQL-only by design, ADR-092526-4391).
- `services/brief_chat.py`'s interview opening carries the recalled,
  provenance-bearing facts (`user_context`) and the Workspace's shared
  Attention projection (`services.attention.list_attention`, #1049) as
  payload data. The deterministic interview phrasing is unchanged — context
  is data, never interpolated prose. Unavailability degrades to an omitted
  key, never to an empty list dressed up as a read model.

Six tests join `test_design_shared_surfaces.py`, driven through the app's
real `/v1/chat/stream` surface:

1. `test_work_opening_recalls_owner_relevant_facts_through_the_shared_user_model`
   — the relevant owner fact reaches the surface with provenance; a foreign
   owner's fact and an irrelevant fact never do (ownership is the store's
   gate, relevance the query's).
2. `test_recall_at_the_design_surface_caps_sensitivity` — a SENSITIVE fact
   scores 0 at this surface even when topically relevant (the `PERSONAL`
   cap is the query default; widening it would be a private disclosure
   policy); a no-overlap task recalls nothing; an explicit service answers
   `[]`, an unavailable one `None`.
3. `test_unavailable_user_model_omits_the_context_and_keeps_the_interview_deterministic`
   — no shared service ⇒ no `user_context` key, deterministic phrasing
   byte-identical, and recall answers `None` rather than asserting an empty
   model.
4. `test_work_opening_carries_the_shared_attention_projection` — a real HITL
   pause in the Workspace reaches the opening turn through the shared #1049
   projection, classified by the projection (the surface does not re-rank).
5. `test_attention_outage_degrades_to_an_omitted_key` — a projection outage
   omits the key and never fails the work opening.
6. `test_resolver_refuses_to_compose_without_postgres` — the resolver
   answers `None` for a non-PostgreSQL deployment; no process-local twin.

Red-first evidence (pre-repair head `183445ae`, tests copied into a throwaway
worktree at that head): **3 failed, 2 errors, 1 passed** — the two shared-surface
HTTP tests and the resolver test failed, the recall unit tests errored on the
absent module (the composition did not exist), and only the outage-degradation
control passed, because "the key is omitted" is the invariant that test pins
across both repair states. Post-repair: 6 passed. `test_chat_brief_interview.py`
(19 passed), `test_attention_projection.py` + `test_brief_commit.py` (38 passed,
32 skipped) confirm no regression on the surfaces touched.

This is a bounded composition repair; the milestone #7 acceptance accounting
beyond row 18 is unchanged — see the Round 12 section of
`docs/implementation/issue-7-handoff.md`.
