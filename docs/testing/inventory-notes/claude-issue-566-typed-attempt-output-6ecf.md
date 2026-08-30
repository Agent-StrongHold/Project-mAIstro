---
inventory-delta:
  packages/maistro-core/tests: +20
---
# claude-issue-566-typed-attempt-output-6ecf

Three new files, twenty new tests, nothing moved or deleted.

`test_typed_attempt_output.py` (+6) holds the serialization contract for
`NodeResult.output` (#566). Four of the six fail on `develop`: a typed output
serialized through the declared union's empty `BaseModel` schema, so a node
returning a model persisted as `{}`. The other two are the controls that keep
the fix honest — a plain mapping and an absent output must come back exactly as
they went in, and both already passed.

`test_typed_output_recovery.py` (+10) holds the disposition of Attempts already
written emptied. One case restores (the Attempt its NodeRun accepted, named by
id in `AcceptedNodeOutcome`); the rest of the file is the boundary — a
superseded retry, an unaccepted NodeRun, an accepted Attempt with no stored
output, an Attempt that genuinely produced its value, an Attempt with no result
at all, a read-only survey across records, and the two version cases that let
the repair be written back at all. Most of these assert that recovery leaves
things *alone*, which is the property worth the test count: a repair that
guesses is worse than the gap it fills.

`test_repair.py` (+4) drives the `maistro repair` commands an operator actually
runs — survey reports and writes nothing, apply writes back what is restorable
and names what it had to leave empty.
