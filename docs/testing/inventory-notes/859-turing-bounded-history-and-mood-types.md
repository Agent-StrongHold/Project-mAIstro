---
inventory-delta:
  packages/maistro-turing/tests: +9
---
# 859-turing-bounded-history-and-mood-types

Branch: `auto-859`. Base: `develop@5647c34bfb8be091e5935191aed37d56dca974e0`.

Repair round for #859. Two things moved, both inside the Turing package's own
`packages/maistro-turing/tests` suite, so no other suite's count moved.

## What moved

- `packages/maistro-turing/tests` **+9**:
  - `Mood`'s type constraint at the authoritative write seam is now pinned by
    tests instead of only by the diff-coverage gate's measurement of it: a
    non-real value (string, `None`, boolean, list) raises `TypeError`, and a
    non-finite value (NaN, ±inf) raises `ValueError` — four parametrized cases
    plus three, nine node IDs in total, all in `test_self_model_types.py`.
  - the session history bound now holds on every exit path: a turn that fails
    between the user entry and the assistant entry rolls the user entry back,
    so repeated failures cannot grow the session's stored state and a failed
    turn never reaches the next turn's model context (two tests in
    `test_runtime.py`).

## Why

The first is the diff-coverage floor: `packages/maistro-turing/src/maistro_turing/self_model/types.py`
carried the new type/finite checks at 66.7% of its changed lines (the two
`raise` statements were never executed), so the per-file 90% line floor failed
the coverage gate. The tests are the evidence the gate asks for, not padding:
each one fails against the pre-constraint implementation.

The second closes a review finding on the bound this change introduced —
`MAX_HISTORY_TURNS` was enforced only after a successful turn, so a provider or
classifier failure left the user entry behind and the declared bound was not
true of the code that shipped it. Both new tests fail against the
pre-fix runtime.
