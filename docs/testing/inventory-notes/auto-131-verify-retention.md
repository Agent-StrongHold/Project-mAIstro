# Issue #131 verification — retention past protected parents

Independent re-validation at head 6b6e0684 (develop 0ab0bb69 merged into
auto-131). No test inventory change: this note records verification only.

The two prior findings were re-derived and re-executed, not trusted:

1. `max_retained=2` reproduction with a terminal chat parent holding a terminal
   child now sweeps past the protected parent: the younger terminal chat Run is
   deleted, the window stays at `max_retained + protected`, and no
   `RunIntegrityError` escapes the sweep (`ChatRunAdmitter._sweep` catches and
   continues). Reproduced out-of-tree; bound held across a further 4-turn burst.
2. The coverage gap is closed by
   `test_retention_walks_past_a_terminal_parent_with_a_child`; the focused
   four-file suite passes (88 passed), `ruff check .` passes, and both
   suite-inventory gates match the recorded counts.
