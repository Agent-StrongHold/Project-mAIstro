---
inventory-delta:
  tests/: +28
---
# claude-issue-605-matrix-census-bands-aa3f

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

`tests/test_check_convergence_matrix.py` and
`tests/test_check_reachability_dispositions.py` — 28 node IDs for
SPEC-082926-061d (#605).

Seventeen distinct new test functions; two of them are parametrised (four worlds
of the two-branch pair, ten points along the share vocabulary), which is why the
node count runs ahead of the function count.

Six of the seventeen exist because the per-file diff-coverage gate found real
gaps rather than because an acceptance criterion asked for them: the `--census`
and unknown-flag paths through `main`, a census over a module no row owns, a
zero-module subsystem, and `main`'s two failure exits. The last of those found a
defect while being written — the failure message called `Path.relative_to`, which
raises rather than reports when the matrix is outside the repo — so the message
now goes through `os.path.relpath`.

Nothing was removed. Two existing tests were **rewritten in place** rather than
added to, because the thing they asserted no longer exists:
`test_a_stale_reachability_count_fails_with_both_numbers` became
`test_a_stale_share_fails_with_both_words_and_the_exact_counts`, and
`test_a_wrong_total_fails_even_when_the_unreachable_count_is_right` became
`test_a_word_outside_the_vocabulary_lists_the_five`. The second is the honest
replacement, not a weakening: "a wrong total" was a property of the transcribed
cell, and ADR-082926-061d removes the total from the document. What a wrong
total used to catch — a subsystem that silently grew an *unreachable* module —
is now pinned in `test_check_reachability_dispositions.py`, on the gate that
actually owns that requirement, by the mutation rather than by prose. Those two
tests are the +2 there; the other +20 are in the matrix suite.

The four-world parametrisation is deliberately eight modules wide rather than
the three the rest of the file uses. At three modules every share word is one
addition away from a boundary, so a pair-of-branches test built on the existing
fixture would have passed for the wrong reason — and did, on the first attempt,
until 1-of-5 landed exactly on the `few` boundary and failed.
