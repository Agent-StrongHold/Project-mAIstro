---
inventory-delta:
  tests/: +11
---
# claude-issue-631-anchor-must-resolve-9677

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

One new file, eleven tests, nothing moved or deleted.

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
