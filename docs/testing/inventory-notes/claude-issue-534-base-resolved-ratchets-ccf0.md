---
inventory-delta:
  tests/: +20
---
# claude-issue-534-base-resolved-ratchets-ccf0

The second round on #534, covering the five findings Codex raised against the
first. Purely additive; no test was removed, and the three that changed shape
changed because the seams they substitute did.

- 12 in `tests/test_ratchet_provenance.py`:
  - `TestABaseThatIsTheCandidateIsRefused` (5) — the push-event shape, where
    `origin/develop` resolves to the pushed HEAD and the ledger becomes its own
    oracle. The condition is narrow on purpose, so the class pins both sides of
    it: a clean checkout sitting on its own base is refused and the refusal
    names the variable that fixes it; naming the pre-push revision is the way
    through; uncommitted work is a *real* comparison and is left alone (that is
    the local pre-commit loop); and an untracked file an earlier CI step wrote
    does not switch the guard off.
  - `TestTheNullShaIsNotABase` (4, three of them parametrised) — the first push
    to a branch carries git's all-zero sentinel in `github.event.before`. That
    is the absence of a base rather than an unusable one, so it falls through
    to the trunk instead of failing every new `feat/*` branch.
  - One in `TestUnreadableTrustIsAFailureNotAFallback` — `cat-file -e` returns
    nonzero for "no such path" *and* for "no such object", and reading the
    second as the first let a zero-debt ratchet pass without ever reaching its
    oracle.
  - Two in `TestAuthorizationsAreASeparateAct` — a grant the change brings with
    it authorizes nothing (the finding: a separate file with prose reasons made
    the grant reviewable, not *prior*), and a grants file that parses to
    something other than an object is refused.
- 8 in `tests/test_check_wiring_reads.py`:
  - `TestBothReadsOfTheBaseComeFromOneCommit` (1) — `main` resolves the base
    once and hands the answer to the grants read, rather than letting the two
    look it up independently against a ref that moves.
  - `TestAnAuthorizationPermitsTheIncreaseItDoesNotRecordIt` (3) — an authorized
    field the candidate never banks used to pass *and print that the ledger
    matched*, leaving the trusted floor permanently dependent on the grant.
  - `TestTheMetricDefinitionHasToMatch` (4) — the constant was printed and never
    read back, so bumping it changed the provenance line and not the verdict.
    A floor measured under another definition is refused, a ledger predating
    versioning is grandfathered, `--update` persists the declared version, and
    the repo's own committed ledger carries one — without that last, the check
    could never fire on the real file.

`_base_state()` replaced the bare `_trusted()` substitution at every call site
that reaches `main`. The two reads of the base have to move as a pair now: a
test that fakes the ledger and leaves the grants to resolve for real asks git
for a base SHA that does not exist, which the shallow `test` job reported as
three merge-base failures whose cause was a half-built fixture.

`TestAuthorizationsAreASeparateAct` moved off `tmp_path` and onto real
repositories: grants are read from the base revision now, and only a repository
can express the difference between "already landed" and "added in this change".
Three tests elsewhere gained a commit on the candidate branch, because the
fixture leaves it sitting exactly on its base and that is now refused.
