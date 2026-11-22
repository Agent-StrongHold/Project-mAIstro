---
inventory-delta:
  packages/maistro-registry/tests: +3
---
# auto-26-repair-stale-index-gate

Verifier evidence for #26's acceptance criterion "Corpus refresh/removal
invalidates stale indexed content": the corpus fingerprint was recorded
on every saved index but *enforced* nowhere — `maistro-registry search
--index` / `eval --index` served a saved artifact whose corpus had since
gained, lost, or changed a document, answering from stale provenance.

Repair (production behavior, not scanner cosmetics):

- `retrieval/index.py` gains `stale_index_reason(index, documents)` —
  the single freshness seam; `None` when the loaded fingerprint matches
  the current corpus, otherwise a refusal naming both fingerprints and
  the rebuild command.
- `cli.py::_load_searcher` now runs that check on every prebuilt-index
  use; `cmd_search`/`cmd_eval` refuse with exit 2 and the message on
  stderr. Fresh indexes behave exactly as before.

New tests (+3):

- `test_retrieval_index_search.py::test_stale_index_reason_enforces_freshness_against_the_corpus`
  — fresh corpus stays servable; an addition and a same-path content
  edit are both reported stale, with the rebuild command named.
- `test_retrieval_cli.py::test_search_refuses_a_stale_saved_index` —
  the addition leg through the CLI: exit 2, "stale index" + rebuild
  hint on stderr, no results printed.
- `test_retrieval_cli.py::test_eval_refuses_an_index_stale_to_edited_content`
  — the content-edit leg through `eval`, proving one freshness contract
  for every consuming command.

`packages/maistro-registry/README.md` documents the enforced
invalidation in the `index.py` bullet so the seam contract stays
written next to the pipeline description.
