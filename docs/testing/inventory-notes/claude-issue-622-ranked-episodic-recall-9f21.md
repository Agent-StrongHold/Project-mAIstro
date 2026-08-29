---
inventory-delta:
  packages/maistro-core/tests: +13
  packages/hive-conductor/backend/tests: +0
---
# claude-issue-622-ranked-episodic-recall-9f21

`packages/maistro-core/tests/memory/test_ranked_recall.py` (+13, new). Nothing
was deleted; three tests moved *within* `test_retrieval.py` in place — the class
that exercised `ScoredEpisodicRetrieval._keyword_similarity` now exercises
`ranking.keyword_overlap`, which is where that term lives once there is one of
it. Same three cases, same file, so the count is unchanged there.

The thirteen are six criteria and their controls. Every criterion that could be
satisfied by a broken implementation has one:

- **relevance over insertion order** (AC-1) — and the same assertion with the
  two memories stored in the opposite order, because a ranking that happened to
  agree with store order once would satisfy the first without ranking anything;
- **ranking through the protocol** (AC-2) — against a store that is not a
  subclass and has no `_memories`, plus a check that the scope axes reach the
  store rather than being applied in Python afterwards, which a reranker that
  pulled the whole table would otherwise pass;
- **whole memories under budget** (AC-3) — and a budget that fits everything,
  because a packer that dropped everything would satisfy the first;
- **the ADR-091 weight bands** (AC-4) — always-include survives a budget of
  zero, below-budget is excluded however relevant;
- **the assembled context reaches the prompt** (AC-5) — and cannot close a
  delimiter block it does not own, which is the stored-injection shape
  learnings already neutralize and which episodic memories reach by the same
  route;
- **one formula, one scale** (AC-6) — a bounded vector similarity outranking a
  partial lexical match, the two rankers agreeing, and the score being ADR-080's
  product.

Each was verified by mutation. Restoring the character slice fails AC-3 and
AC-4; making `layer1` ignore its query fails both AC-1 tests; dropping the
always-include clause fails AC-4; removing the delimiter sanitizer fails AC-5;
returning the lexical term to a raw count fails AC-6.

That last one is worth recording because the first version of it did **not**
fail: `len(q & c)` and `len(q & c) / len(q)` are the same ordering for a fixed
query, so no lexical-only case separates them. The test now uses the case that
does — a four-word query, two memories sharing no vocabulary, and an embedding
client — where the scale decides and the count makes the vector term unable to
matter.

One existing Conductor test changed rather than moved:
`test_maistro_core_adapter.py::test_start_passes_container_prompt_manager_to_agent_factory`
now also asserts the assembly policy the Container selected is the one the
agents receive. Its claim was already "Hive consumes what the Container
selected"; this is one more wiring under the same claim, and its double gained
the field, so the suite count is unchanged.
