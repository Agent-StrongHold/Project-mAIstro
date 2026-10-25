---
inventory-delta:
  tests/: +19
---

# One Ruff owner per CI event (#1357)

Refs #1357 and #160. This implements the Ruff portion of the original
`b3f0ef5f` deduplication intent, adapted to current workflow scopes. It does
not merge the old branch or close the wider audit or #1605.

Quality already executes `uv run ruff check .` and
`uv run ruff format --check .` unconditionally at the repository root using
the shared uv setup and locked environment. Its required Quality gate covers
unfiltered PRs, merge groups, protected pushes and the accepted topic prefixes.
The CI copy remains for the one push profile Quality does not cover:
`merge/main-into-integration`. No workflow/job/check is removed or added, and
all other commands, environments, profiles, permissions and thresholds remain.

The full original CI file matched Git blob
`7f167efd6ec2d96b2586b9db75b7bc7625137fc7`, confirmed again on
`develop@0456938b69e1b30c5103079308b876dbb2dd8330` before publication.
The candidate workflow blob is `11945da4d70e3685766f75c4f00ea926b8210241`.
Parsed full-workflow comparison proves the only semantic differences are the
two Ruff step conditions. Four incidental comment wording differences do not
change the parsed workflow. No historical runtime/migration/test rollback is
included.

Nineteen focused tests passed locally under Python 3.13.5. They check command
ownership, fallback scope, required Quality contexts, and mutations that delete,
narrow, relocate or tolerate the remaining checks. Local testing used the
complete hash-verified CI file plus source-derived fixtures containing the
fetched Quality/protection fields relevant to the contract. It is not a claim
of testing a complete local monorepo. In repository CI the same tests load the
actual complete workflow and protection files. Full exact-head CI, actionlint,
Ruff, inventory and independent review remain required.

Live required-context reads on 2026-09-27 confirmed the Quality gate is required
by both develop ruleset 21421373 and main ruleset 21701487. Other declared/live
queue differences are documented on #564, not changed by this optimization.

This removes two duplicate analyzer invocations on common events without adding
runners or changing the retained analyzer commands. No measured net runner-minute
or wall-time improvement is claimed yet. The loss of CI's earlier duplicate
fail-fast point and the small regression-test cost belong in that measurement.
