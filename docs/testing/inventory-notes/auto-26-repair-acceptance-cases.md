---
inventory-delta:
  packages/maistro-registry/tests: +3
---
# auto-26-repair-acceptance-cases

CI-repair for the #26 candidate: the issue names six corpus cases the
tests must cover, and three were missing. They now live in
`test_retrieval_corpus.py`:

- `test_renamed_source_keeps_stable_id_but_moves_the_fingerprint` — a
  renamed file keeps its registry id (identity comes from validated
  front matter, not the filename), keeps its content version (identical
  bytes), and still moves the corpus fingerprint so an index rebuilt
  over it is a different corpus state.
- `test_superseded_decision_is_retrieved_with_its_status` — a
  `status: Superseded` ADR is findable, and the hit's provenance record
  and rendered line both carry `[Superseded]`, so historical material
  can never pose as active governing authority.
- `test_duplicate_identity_keeps_both_documents_addressable` — two
  files claiming one registry id both survive loading with distinct
  paths/versions, and a search returns both, surfacing the ambiguity
  instead of silently electing one answer.

Also extended (no node-count change):
`test_fingerprint_moves_with_any_corpus_change` now covers the removal
leg of "corpus refresh/removal invalidates stale indexed content" — a
deleted source's id is gone from the rebuilt index and the fingerprint
returns to the pre-addition value.

Corpus sizes in the new tests use five documents because the measured
df-share ceiling (0.5) correctly rejects every term of a tiny corpus —
the same reason `test_retrieval_expansion.py` builds four.
