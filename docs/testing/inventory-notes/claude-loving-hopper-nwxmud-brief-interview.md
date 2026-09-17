---
inventory-delta:
  packages/maistro-core/tests: +11
---
# Requirements interview before a Goal commit (SPEC-091726-7c2a, #774)

Eleven new collected cases, all in
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
assumed; after that, turns set optional fields or become notes.
