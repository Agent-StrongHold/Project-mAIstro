---
inventory-delta:
  tests/: +7
---
# claude-issue-267-hive-conductor-ac-scanning

Seven new node IDs, all in `tests/test_check_ac_state.py::TestPassingPerRoot`.
Nothing removed or reparametrised.

They exist because #257 put `scripts/` inside the diff-coverage gate, and this
change rewrote `passing_ac_ids` — so the gate asked for the tests, correctly. It
caught them at 9.1% of 11 changed lines before they were written.

The property they defend is the distinction the whole script is built on: an
empty set means "the suite ran and nothing passed", `None` means "we do not
know". Three of the seven are about not confusing the two.

`test_one_unmeasured_root_takes_the_whole_answer_down` is the load-bearing one.
Now that each root runs as its own pytest session, returning the union of the
roots that *did* run would report every criterion proven in a healthy root as
not passing — a fabrication rather than a gap, and one that would fail the
`design_coverage` floor on a number nobody actually broke. That is not
hypothetical: it is what a single combined session did when
`packages/hive-conductor/backend/tests` joined `testpaths` and the top-level
name `config` collided, measured at 17.24% → 0.0%.

`test_a_root_with_no_markers_is_empty_not_unmeasured` covers pytest's exit code
5, which per-root is the ordinary case — most roots carry no `ac` markers at
all — and was unreachable while every root shared one session. Reading it as a
failed measurement would make the common case indistinguishable from a broken
one.

The rest: no existing root is unmeasured rather than empty; outcomes union
across roots and each root really gets its own session (asserted on the call
order, not just the result); an interrupted session (exit 2) is unmeasured; a
completed session reports what passed even when some marked test failed (exit
1); and a session that never started — a timeout, a missing interpreter — is
unmeasured rather than evidence about criteria.

`subprocess.run` is faked rather than really invoked: these are tests about how
the script *interprets* a session's outcome, and spawning eleven real pytest
runs to assert that would be testing pytest.
