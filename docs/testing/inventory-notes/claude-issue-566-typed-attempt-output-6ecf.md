---
inventory-delta:
  packages/maistro-core/tests: +9
---
# claude-issue-566-typed-attempt-output-6ecf

One file, nine tests, after two Codex reviews cut this change back to what it
can actually prove.

`test_typed_attempt_output.py` holds the serialization contract for
`NodeResult.output` (#566). Four cases fail on `develop`: a typed output
serialized through the declared union's empty `BaseModel` schema, so a node
returning a model persisted as `{}`. Two more cover `RootModel` outputs, whose
root is a list or a bare scalar — the review found that the first fix made
those *worse*, serializing them correctly and then failing validation on the
way back, where the old contract had at least lost them silently. The last two
are controls: a plain mapping and an absent output must come back exactly as
they went in, and both already passed.

Every case is mutation-verified. Reverting the union to `dict[str, Any]` fails
the two root-model tests and leaves the rest passing, which is the
discrimination that makes them worth their count.

Two test files were **removed**, not added: `test_typed_output_recovery.py`
and `test_repair.py`. They exercised a repair aimed at `SqliteDurableRunStore`,
which production does not wire — so they proved the repair worked against a
store nothing uses. The repair and its CLI door went with them, and #637
carries the real one against the canonical `RunStore`. Tests that pass because
they share the code's wrong assumption are worse than no tests, and deleting
them is the honest correction.
