---
inventory-delta:
  packages/hive-conductor/backend/tests: +0
  packages/maistro-design/tests: +0
  packages/maistro-core/tests: +1
---

# 777 salvage: pin Attempt's serialization-mode JSON schema against wrap-serializer annotation collapse

Lane L777 (issue #777) round 279 salvage commit. One production edit arrived
uncommitted in `packages/maistro-core/src/maistro/runs/model.py` and one test
pins the contract it restores.

## Production change

`Attempt._serialize_attempt_without_unknown_cause` (pydantic wrap serializer)
dropped its `-> dict[str, Any]` return annotation, with an explanatory comment
and `# type: ignore[no-untyped-def]` for mypy strict. Behavior of
serialization is unchanged: the unknown `cancellation_cause` key is still
omitted and a known cause still round-trips.

## Why the annotation was wrong (proven, not cosmetic)

On pydantic 2.13.5, a model with a wrap serializer derives its
**serialization-mode** JSON schema from that serializer's return annotation.
With `-> dict[str, Any]`, `Attempt.model_json_schema(mode="serialization")`
collapses to `{"type": "object", "additionalProperties": true}` — every field
hidden from schema consumers. Validation mode (the default) is unaffected,
which is why the pre-existing
`test_the_field_stays_declared_in_the_model_schema` passed at the annotated
HEAD. Empirical probe (stand-in model and real `Attempt`):

- annotated `-> dict[str, Any]`: serialization-mode `properties` absent,
  `additionalProperties: true`;
- unannotated (this change): all 16 declared properties present, including
  `cancellation_cause`.

## Test added

`packages/maistro-core/tests/runs/test_attempt_cancellation_cause_model.py::
TestTheSerializerOmitsOnlyTheUnknownCause.test_the_serialization_mode_schema_keeps_every_declared_field`
asserts the serialization-mode property set equals
`LEGACY_PAYLOAD_FIELDS | {"cancellation_cause"}`, so a future re-annotation
fails this contract instead of silently hiding the model shape.

## Relationship to issue #777

No #777 acceptance criterion is touched: the issue remains
dependency-blocked (#804/#805/#806/#53/#774/#776/#93/#95 and parent #773 open
in the freshest capture). This commit only banks validated in-lane salvage so
the worktree is clean.
