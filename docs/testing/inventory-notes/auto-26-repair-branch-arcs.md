---
inventory-delta:
  packages/maistro-registry/tests: +3
---
# auto-26-repair-branch-arcs

CI-repair for the #26 candidate: the coverage gate failed
`retrieval/expand.py` at 77.3% of changed branch arcs (floor 80%), with
partial arcs at the completion-parse cleanup lines. Three tests pin the
arcs the diff gate named:

- `test_expander_rejects_non_string_completion_content` — a numeric
  `choices[0].message.content` raises instead of being coerced (the
  raise-not-degrade discipline, non-string half).
- `test_expander_drops_non_string_blank_and_duplicate_terms` — a
  non-string element, a blank-after-strip term and a duplicate term are
  all dropped, so only the real term reaches the index.
- `test_expander_rejects_fenced_prose_without_an_array` — a fenced
  response whose chunks contain no `[` exhausts the fence loop and still
  raises "no JSON array" (the loop-without-break half of the fence scan).

The remaining partial arc (`isinstance(parsed, list)` after
`json.loads`) is defensive and unreachable by construction — a slice
anchored at the first `[` can only parse as an array — so the file now
clears the per-file branch floor without contorting the code.
