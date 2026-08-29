---
inventory-delta:
  tests/: +4
---
# claude-issue-616-stacked-fold-evidence-c3dc

`tests/test_check_ac_state_ratchet.py`: +4 net, and the number badly understates
what moved. Five existing tests were **rebuilt**, not edited, and four are new.

The five were vacuous. They used the `ceilings` fixture, which points
`ac_state_notes.ROOT` at a directory that is not a Git repository — so
provenance falls back to reading the worktree, the *base* fold and the
*worktree* fold were the same set of notes, and every one of them passed with
`banked_bound` stubbed out entirely. That stub is the pre-#609 behaviour they
claimed to rule out, so #610 shipped its own change with no executable
evidence. Verified by mutation both ways: all five green under the stub before,
and under the same stub now the block goes red.

They run against a real repository now — `develop` holds only the weaker note,
the branch commits the stronger ones on top, so the two folds genuinely differ.
The notes are *committed* on the branch rather than left dirty because the
resolver refuses a base that resolves to HEAD itself, and rightly: the baseline
would otherwise be read from the commit under judgement.

`test_the_harness_can_tell_the_two_folds_apart` is the control and the reason
the rest is evidence: it asserts `bounds()` reads 20.0 while `banked_bound()`
reads 22.0. Without it, a later fixture change could collapse the two again and
nothing here would notice — which is exactly how this happened the first time.

Three more cover the fold's own error paths, both newly reachable because the
fold reads every note in the tree while the one-note rule it replaced skipped
`_baseline.json`:

- a worktree note banked without `--run-tests` is refused rather than folded
  into a `--run-tests` target, with the matching negative case so a check that
  refused everything could not satisfy it;
- a malformed `_baseline.json` produces the gate's diagnostic instead of a
  traceback.

`scripts/check-ac-state.py` gained `_exact_target` and `_report_movement`, both
extracted from `ratchet` rather than newly written: the fold's two refusals
pushed that function past the complexity ceiling, which was the linter noticing
that "compare" had become "compare, and decide whether comparing is allowed".
No test names either helper — they are exercised through `ratchet`, which is the
door every caller uses.
