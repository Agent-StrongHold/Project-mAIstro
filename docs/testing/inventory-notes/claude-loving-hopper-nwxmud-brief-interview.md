---
inventory-delta:
  packages/maistro-core/tests: +12
  packages/hive-conductor/backend/tests: +6
---
# Requirements interview before a Goal commit (SPEC-091726-7c2a, #774)

Eighteen new collected cases. Twelve in
`packages/maistro-core/tests/agents/test_brief_interview.py`, binding the
spec's nine criteria with `@pytest.mark.ac("SPEC-091726-7c2a/AC-N")`: a work
request opens an interview and nothing is committable; one required question
at a time in script order, with the brief-so-far summary; answers in the
opening turn or the record are not asked and the record never overrides the
person; free text matches an option or is carried verbatim; an answer that
fits another open field is routed there while the current question stands;
"you decide" takes a marked default or is refused for the subject; "change"
re-answers any field and "never mind" drops with nothing written; commit is
refused until every required field is known and the draft lists what was
assumed; after that, turns set optional fields or become notes; and an
interview answers one script only.

Six more in `packages/hive-conductor/backend/tests/test_program_brief_routes.py`,
for the `/v1/program/brief` endpoints that host the interview: a request
naming no workspace is refused; start opens an interview and the draft is
refused with the missing fields; answers move it, the opening turn's channel
is never asked and the draft names what was assumed; "never mind" drops and
delete forgets; two workspaces hold independent interviews; an unknown
script is refused.
