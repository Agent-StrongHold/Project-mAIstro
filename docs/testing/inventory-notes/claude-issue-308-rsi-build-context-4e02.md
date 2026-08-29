---
inventory-delta:
  tests/: +58
---
# claude-issue-308-rsi-build-context-4e02

The second round on #308, covering the five findings Codex raised against the
first. All forty are in `tests/test_check_build_context.py`, purely additive.

- `TestTheMatcherIsDockersAndNotFnmatchs` (18, parametrised) — the gate's
  verdicts are only as good as its matcher, and the matcher was `fnmatch`,
  whose `*` crosses a `/`. So it read `*.p12` as denying
  `packages/provider/client.p12` when Docker denies only `client.p12` — the
  exact root-relative-pattern defect it existed to catch. The parameters pin
  both directions for each construct: segment-confined `*`, `**` spanning
  segments, the leading-`/` top-level form, `**/` at any depth, character
  classes, and Docker's rule that naming a directory excludes everything under
  it.
- `TestAnExceptionCannotUndoADenial` (4) — an exception written below the
  secret rules re-includes what they denied while every literal-presence check
  still passes. One test places the exception below and fails, one places it
  above and passes (which is why the real files now put the secret denials
  last), one refuses an exception nobody wrote down, and one requires each
  entry in `EXPECTED_NEGATIONS` to carry its reason.
- `TestSecretsAreDeniedAtEveryDepth` (7, six parametrised) — dropping each
  recursive private-key pattern lets the key under `packages/` back in. The
  seventh states the misreading directly, because the two spellings look
  interchangeable and are not.
- `TestTheBuildStillGetsWhatItNeeds` (2) — a gate that only checked denials
  could be satisfied by denying everything, so the generated bundle and
  `.env.example` are probed for survival.
- `TestARuleHereCanBreakABuildOverThere` (5) — the ignore file governs every
  `docker build` rooted at the repository, and the gate had only ever read the
  RSI runner's Dockerfile. `**/dist` silently removed
  `packages/hive-conductor/frontend/dist/` from the backend image's context,
  where its Dockerfile copies it. One test runs the new check over every
  tracked Dockerfile for real.
- `TestTheRunnerImageCarriesTheFixturesItsTestsRead` (4) — the two repository
  fixtures the scoped test command reads, the coupling that makes them
  required, and `.gitignore`.

No test was removed. `_complete()` was reordered rather than rewritten: it now
mirrors the real files' structure, because rule ORDER is part of what the gate
checks and a helper that produced a passing-but-wrongly-ordered file could not
express the exception tests at all.

## Plus 18, from removing a suppression rather than adding a test

The autonomous-merge admissibility check flagged an INTEGRITY finding on this
branch: a `pytest.skip` in `tests/test_check_build_context.py`. It was mine,
from the first round, and it was hiding something.

`TestEverySecretPatternIsDenied` was parametrised `range(9)` with a skip for
indices past the end of `MUST_DENY`. When `MUST_DENY` grew from 9 to 27 the
skip never fired, so nothing said anything -- the test simply stopped covering
eighteen patterns, including every recursive private-key form this change
added to close a P1. A parametrisation built from a hand-copied length
under-tests silently the moment the thing it counts grows, and the skip that
was there to make that safe is exactly what kept it quiet.

It now parametrises over the real `MUST_DENY`, which is why the count moves by
eighteen: the same one test, finally applied to every pattern it claims to be
about. The module is loaded at import for that, so the parametrisation can read
the set rather than a number.
