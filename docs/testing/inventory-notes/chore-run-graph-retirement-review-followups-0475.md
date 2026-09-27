---
inventory-delta:
  tests/: +4
---
# chore-run-graph-retirement-review-followups-0475

Two Codex review findings on #1524, which merged before they could be pushed
to it (its branch was locked in the merge queue).

**Added to the retired-guidance gate (+4, `tests/`).**
`TestRetiredRunGraphImport` in `tests/test_check_retired_guidance.py` pins the
`pre-durable-run-graph` entry #1524 added to `quality/retired-guidance.json`.
The scan is line-based, so a parenthesised import that puts `run_graph,` on
its own line went unreported; the entry now also matches a bare `run_graph`
import-list line. The four cases cover the single-line import, the
multi-line import, and the two lines that must stay clean (the surviving
`HarnessEnvironment.run_graph` fixture method, and a line citing the
retirement).

**Strengthened, no count change.**
`TestBeamWidth::test_a_beam_keeps_the_best_of_several_generations` asserted
only `success`, which a width-1 traversal also satisfies. It now asserts three
generations and that the `strong` plan is the one kept, and fails if the beam
width is set back to 1.
