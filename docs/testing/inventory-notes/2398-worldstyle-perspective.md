---
inventory-delta:
  packages/maistro-canvas/tests: +14
---
# 2398-worldstyle-perspective

Issue #2398: `WorldStyle.perspective` (flat|one_point|two_point|isometric)
never reached asset-path image prompts — `_serialise_world_style` serialized
era/realism/architecture/vehicles/fauna/palette and dropped perspective, which
is why the field (originally mislocated on `GroundPlane` by the issue text;
deleted there by #2406) surfaced as dead code. The fix gives `WorldStyle` the
field, plumbs it through `WorldStylePartial`/`merge_world_style`, the store
serde, and the API model, and serializes it into prompts.

+14 maistro-canvas tests, all guarding the serialization contract:

- compositor (7): golden `_serialise_world_style` shape with perspective
  (fails against the pre-fix output, which omitted the term), default flat,
  `compose_prompt` carriage, base-perspective preservation and partial
  override through `merge_world_style`, StyleVolume page-range override,
  and an end-to-end `plan_render` prompt assertion.
- store (5): ser/deser round-trip, persisted-key presence, legacy-row default
  (rows written before the field existed load as flat), partial-deser None
  inheritance, and a book round-trip of both base and partial perspective.
- routes (2): API round-trip of a non-flat perspective and the legacy-payload
  default (payloads without the field stay valid, read back flat).

