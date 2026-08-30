---
inventory-delta:
  packages/maistro-core/tests: +72
---
# claude-issue-637-repair-emptied-attempt-outputs-6747

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

All 72 are added and nothing was removed or renamed: two new files, and the
count is exactly what they collect.

`packages/maistro-core/tests/runs/test_attempt_result_repair.py` — 60 node IDs.
Most are one set of cases run against all three store twins (`[memory]`,
`[sqlite]`, `[postgres]`) through the shared `spine` fixture, because
`repair_attempt_result` has to mean the same thing on each backend. Repair here
is deliberately *not* a shape heuristic: `output: {}` is indistinguishable from
a genuinely empty output, so an Attempt is repairable only where a second copy
survives on the NodeRun, and the discriminator is exact rather than "looks
empty". `TestClassification` pins each disposition, including the two refusals
that must be reported rather than guessed at; `TestTheRepair` pins what moves
and what does not; `TestASurveyWritesNothing` holds the dry-run property from
the store side; `TestACappedSweepSaysSo` holds that a truncated sweep says so.

Twelve of the 60 answer review findings on this PR (Codex, #690), and three of
those are not parametrized because the property is not per-backend:

- `TestAnEmptyLogicalRecordIsNotASecondCopy` (4) — a node that genuinely
  returned `{}` leaves `NodeRun.result == {}` beside the Attempt's
  `{"output": {}}`. Those compare *unequal*, one being a projection and the
  other an envelope, so the record read as repairable, `--apply` wrote `{}` back
  unchanged, and every later sweep reported it again.
- `TestTheSweepStaysInsideItsWorkspace` (2) — two real Workspaces in one store,
  because the store refuses a Project belonging to another Workspace, which is
  what makes two genuine Workspaces the only honest way to pose the question.
  The filter lives in `survey`, so one backend is the right scope for it.
- `TestTheSqliteRepairCommitsBothCopiesTogether` (1) — counts `_flush` calls.
  Two commits are two chances to stop between them; against the previous code
  it reads `assert 2 == 1`.

`packages/maistro-core/tests/cli/test_repair.py` — 12, covering the
`maistro repair` command: which store a `sqlite:` and a `postgresql:` URL each
open, that surveying without `--apply` writes nothing, that applying writes the
repair and reports a count, that an unrepairable finding is shown with its
reason, and that a capped sweep is announced. Four are from the same review —
the survey names the Workspace it confined itself to, it states that archived
runs were not examined (on a clean sweep as well as a dirty one), and neither
backend primes the spine, since priming creates the Root Project and this
command only reads until it is told to apply.
