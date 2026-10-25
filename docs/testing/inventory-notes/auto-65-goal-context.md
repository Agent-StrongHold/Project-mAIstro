---
inventory-delta:
  packages/maistro-core/tests: +6
---
# auto-65 Goal-context provenance contract

#65 (M3) needs a Goal context a goal-driven Run carries in its provenance
(#458) — the same leaf-module pattern `runs.sources` uses for scheduled
occurrences, so a producer and a reader that cannot import each other can still
agree on the strings. `maistro.runs.goal_context` is that one spelling: the
provenance keys a Run records and the fail-closed reader every projection must
use.

Six new tests pin the contract: a full goal context round-trips every
recorded field; the minimum is `goal_id` plus the exact `goal_revision`;
provenance naming a goal without its revision projects nothing (inventing a
revision would let a later Goal revision rewrite which history owns the run);
blank identity is absence, not a context; non-string values name no context;
and recorded-optional fields are never defaulted to synthetic values.
