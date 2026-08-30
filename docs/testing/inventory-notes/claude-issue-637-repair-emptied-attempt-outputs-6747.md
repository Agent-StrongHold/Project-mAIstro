---
inventory-delta:
  packages/maistro-core/tests: +57
---
# claude-issue-637-repair-emptied-attempt-outputs-6747

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

All 57 are added and nothing was removed or renamed: two new files, and the
count is exactly what they collect.

`packages/maistro-core/tests/runs/test_attempt_result_repair.py` — 48 node IDs
from 16 tests, each run against all three store twins (`[memory]`, `[sqlite]`,
`[postgres]`). That multiplier is most of the delta and it is the point:
`repair_attempt_result` has to mean the same thing on each backend, so the
suite drives one set of cases through the shared `spine` fixture rather than
asserting separately per store.

The cases exist because repair here is deliberately *not* a shape heuristic.
An `output: {}` is indistinguishable from a genuinely empty output, so an
Attempt can only be repaired where a second copy of the result survives — the
NodeRun the reconciliation path wrote it to. The discriminator is exact
(`NodeRun.result != attempt.result`), not "looks empty". So `TestClassification`
pins each disposition `classify` can reach, including the two refusals
(`NOT_ACCEPTED`, `NO_SECOND_COPY`) that must be reported rather than guessed at,
and `TestTheRepair` pins what moves and what does not: the recovered output
lands on the Attempt, an accepted outcome moves with it, the logical projection
is left alone, and a still-running Attempt is refused.
`TestASurveyWritesNothing` holds the dry-run property from the store side, and
`TestACappedSweepSaysSo` holds that a truncated sweep says so instead of
reading as "nothing left to fix".

`packages/maistro-core/tests/cli/test_repair.py` — 9, covering the
`maistro repair` command: which store a `sqlite:` and a `postgresql:` URL each
open, that surveying without `--apply` writes nothing, that applying writes the
repair and reports a count, that an unrepairable finding is shown with its
reason, and that a capped sweep is announced.
