---
inventory-delta:
  packages/maistro-registry/tests: +20
---
# auto-26-repair-governed-egress

CI-repair for the #26 candidate (ed5667d79): its CI run failed the `test`
gate because `maistro_registry.retrieval.expand` called a model endpoint
directly over HTTP — a new direct model egress the trusted base does not
authorize (scripts/check-model-egress.py). The repair routes expansion
through `execute_model_chat` in `maistro.capabilities.providers.llm_gateway`,
the one approved egress module in `quality/model-egress.json`, so the
registry module is no longer a direct caller at all.

Test-count movement, by file:

- `test_retrieval_expansion.py` +3: the transport fakes moved to the
  governed seam, and the single `http failure` case became three
  mapped gateway failures (401 auth, 429 rate-limit, unreachable)
  plus an event-loop discipline case, minus none.
- `test_retrieval_cli.py` +11 (new file): production consumers for the
  audit trail — `search --terms` (drives `matched_terms`) and
  `eval --json` (drives `report_to_dict`, which now serializes
  `matched_relevant`) — plus the retrieval CLI surface the candidate
  had left unexercised (index build/error legs, prebuilt-index and
  custom-ceiling loading, expansion-skip degradation, no-hit and
  threshold-failure paths, and a clean error for `--expand-endpoint`
  without `--expand-model`, which previously raised a bare ValueError).
  These wirings also retire five vulture identities the candidate had
  left unused.
- `test_retrieval_corpus.py` +5: the degradation and walk branches the
  candidate left partial — empty front-matter blocks, a sectionless
  KNOWN-GAPS.md, a KNOWN-GAPS.md with no intro, non-markdown walk
  entries, and `include_known_gaps=False`.
- `test_retrieval_index_search.py` +1: `df_share`/`idf` on empty
  corpora and unseen terms (zero, not a division error or a negative
  weight).

The +20 also closes the diff-coverage failures the candidate's CI run
reported for `cli.py`, `retrieval/corpus.py`, and `retrieval/terms.py`.

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->
