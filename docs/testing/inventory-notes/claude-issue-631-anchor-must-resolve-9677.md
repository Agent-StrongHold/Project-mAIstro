---
inventory-delta:
  tests/: +16
---
# claude-issue-631-anchor-must-resolve-9677

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

One new file, sixteen tests, nothing moved or deleted.

`tests/test_ac_state_anchor_resolution.py` covers the anchor-resolution gate
(#631). Two tests hold the module universe itself -- that it is not silently
empty, which would make the gate vacuous rather than strict, and that it carries
all three identity shapes, since a gate understanding only dotted package names
would reject the Conductor and the tooling and push authors back toward the bare
name that caused this. Four cover the reporting rule, including the empty
string and the unloadable-universe case. Two keep the two failures apart.

The last pair is the load-bearing one. `test_an_unresolvable_anchor_still_reads_
as_reachable_to_the_rung` pins the defect rather than the fix: `_is_reachable`
returns True for a meaningless name, and always will, because it has no way to
distinguish "absent because reachable" from "absent because nothing". That is
the reason the check runs before anything is counted instead of inside the rung,
and a later reader who tries to move it there will fail this test and read why.
Its sibling proves a genuinely unwired module is still resolvable and still not
reachable -- the finding the rung was built for, which the new gate must not
swallow.

The empty-string case earned its place immediately: it failed on first run
against my own implementation, which wrote `if module and module not in
universe`. That short-circuits on `""` -- an anchor written and left blank,
which the rung scores `reachable`. It is the narrowest instance of the very
defect the gate closes, and I had reintroduced it inside the fix.

Verified by counterfactual as well as by unit test: reintroducing one bare
anchor into a real spec fails `check-ac-state.py` with exit 1 and names the
file, the criterion and the string; restoring it passes.

Five more came from the front-matter gate, which rejected the corrected
anchors outright: `@` cannot start a bare YAML scalar, so a scoped identity
has to be quoted, and a regex reader that keeps the quotes then yields
`"'@tool/...'"` -- an identity matching no module and not what the document
says. Both halves are load-bearing and neither is visible from the other; the
resolution gate is regex-based and was content with the quotes, the linter is
YAML-based and was content without them. Four tests pin the quoting (both
quote characters, the unquoted case that must not change, the unmatched quote
that must be left alone) and one asserts every anchor in the *real* corpus
resolves, which is the claim the change actually makes.

That last one is what caught the regression: #628 merged mid-review and
brought five fresh bare anchors, and the corpus test failed on the merge
rather than after it.

One test in this file was itself flaky and is now not. It picked a baselined
module with `next(iter(...))` over a set, so the pick followed the per-process
hash seed. Roughly one run in five it drew one of the 40 baseline entries that
are not module identities, and failed. `min(unreachable & universe)` is stable;
verified across eight explicit hash seeds rather than by re-running and hoping.
The 40 are #651, named in the comment so the next reader does not re-derive
them.
