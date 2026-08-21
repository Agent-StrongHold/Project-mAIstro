# Canvas Layer Model — Behavioural Spec
#
# Sibling to SPEC.md. Covers the typed layer model from
# maistro-engine#ADR-039: scene graph, sockets, asset definition/
# instance split, world style + render style + style volumes,
# generalised asset sheets, and personalisation slots compiled to
# skin bindings.
#
# Format follows the existing SPEC.md (Gherkin scenarios → edge cases
# → invariants), so the same testing pipeline applies.

issue_number: ADR-039
title: "Canvas layer taxonomy, scene graph, asset model, world style"
status: proposed
complexity: L
substrate:
  - maistro-engine#ADR-039
  - maistro-engine#ADR-005
  - maistro-engine#ADR-032

components:
  - name: layers.py
    path: packages/maistro-canvas/src/maistro_canvas/layers.py
    description: "Typed enums, value objects, asset model, world style, pose geometry"

  - name: types.py (extended)
    path: packages/maistro-canvas/src/maistro_canvas/types.py
    description: "New domain errors for the layer model"

  - name: protocols.py (extended)
    path: packages/maistro-canvas/src/maistro_canvas/protocols.py
    description: "AssetSheetService, AssetRegistry, PersonalizationCompiler; widened ImageGenClient.generate"


# ─────────────────────────────────────────────────────────────────────
# ACCEPTANCE CRITERIA
# ─────────────────────────────────────────────────────────────────────

acceptance_criteria:

  # ── Taxonomy migration ────────────────────────────────────────────
  - "LayerKind has exactly seven values: BACKGROUND, STRUCTURE, VEHICLE, PROP, CHARACTER, FX, TEXT"
  - "LayerType remains importable for backwards compatibility"
  - "layer_type_to_kind(LayerType.BACKGROUND) == LayerKind.BACKGROUND"
  - "layer_type_to_kind(LayerType.CHARACTER) == LayerKind.CHARACTER"
  - "layer_type_to_kind(LayerType.OBJECT) == LayerKind.PROP (default)"
  - "layer_type_to_kind(LayerType.TEXT) == LayerKind.TEXT"
  - "layer_type_to_kind on an unknown value raises ValueError"

  # ── Scene graph ───────────────────────────────────────────────────
  - "AssetInstance.parent_id may reference any other instance on the same canvas"
  - "AssetInstance.parent_socket if set names a socket declared on the parent's AssetDefinition"
  - "A child instance with parent_id but no parent_socket is legal and inherits transform only"
  - "Removing a parent instance leaves its children orphaned (parent_id set to a now-missing id); validation raises MissingSocketError on next render"

  # ── Anchor vocabulary ─────────────────────────────────────────────
  - "Anchor enum has exactly three values: GROUND_CONTACT, HORIZON, FLOATING"
  - "All other 'anchors' are expressed as parent_id + parent_socket"

  # ── Asset definition / instance split ─────────────────────────────
  - "AssetInstance.definition accepts either a string registry id or an inline AssetDefinition"
  - "An inline AssetDefinition has empty asset_id and is not stored in the registry"
  - "A registered AssetDefinition has a non-empty asset_id matched to its registry key"
  - "Promoting an inline AssetDefinition to a registered one is idempotent: re-registering an existing asset_id is a no-op"
  - "Editing AssetDefinition.base_prompt invalidates downstream generation caches for every AssetInstance pointing at the definition"

  # ── Asset sheet ───────────────────────────────────────────────────
  - "AssetSheet.refs holds 3-5 source images"
  - "AssetSheet.revision starts at 1 and bumps on regeneration"
  - "AssetSheetService.regenerate_sheet replaces sheet_image and increments revision"
  - "AssetSheet works for any AssetDefinition.kind, not only CHARACTER"

  # ── Pose geometry ─────────────────────────────────────────────────
  - "STRUCTURE accepts only FoundationFootprint pose_geometry"
  - "VEHICLE accepts only WheelAnchors pose_geometry"
  - "CHARACTER accepts only CharacterPose pose_geometry"
  - "PROP, FX, BACKGROUND, TEXT reject any pose_geometry; assigning raises PoseGeometryMismatchError"
  - "POSE_GEOMETRY_FOR_KIND maps STRUCTURE/VEHICLE/CHARACTER to their respective dataclasses"

  # ── Background composition ────────────────────────────────────────
  - "BackgroundComposition carries a required GroundPlane"
  - "GroundPlane.horizon_y is between 0 and 1 inclusive"
  - "GroundPlane.perspective is one of: flat, one_point, two_point, isometric"
  - "Other layers may anchor against the ground plane via Anchor.GROUND_CONTACT or Anchor.HORIZON"

  # ── Occlusion ─────────────────────────────────────────────────────
  - "OcclusionHint.in_front_of and behind reference instance_ids on the same canvas"
  - "An instance referencing itself in occlusion raises OcclusionCycleError"
  - "A cycle between two or more instances raises OcclusionCycleError"

  # ── Personalisation ───────────────────────────────────────────────
  - "PersonalizationSlot.kind is one of: child_name, child_likeness, companion, pet, gift, place_name, pronouns"
  - "ChildProfile.likeness_refs may be empty; rendering with no refs falls back to prompt-only generation"
  - "ChildProfile.accommodations is a tuple; empty when no accommodations apply"
  - "PersonalizationCompiler.compile resolves every PersonalizationSlot to a skin in the parent definition's skin_set"
  - "An unbound PersonalizationSlot raises SkinBindingError"
  - "Compiling is total: every slot is either bound or raises"

  # ── World style ───────────────────────────────────────────────────
  - "WorldStyle requires era, realism, architectural_register, vehicle_register, palette_anchors, fauna_realism"
  - "WorldStyle.realism is one of: cel, painterly, watercolor, photoreal, line"
  - "WorldStyle.fauna_realism is one of: cute, realistic"
  - "merge_world_style(base) == base when no partials are passed"
  - "merge_world_style(base, partial) overrides only the fields set on partial"
  - "merge_world_style(base, p1, p2) applies p1 then p2; later wins on overlapping fields"
  - "A WorldStylePartial with all None fields is the identity under merge"

  # ── Style volumes ─────────────────────────────────────────────────
  - "StyleVolume.page_range is inclusive on both ends"
  - "Multiple StyleVolumes whose page ranges overlap apply in declaration order; later volumes override earlier"
  - "A page outside any StyleVolume uses base WorldStyle only"

  # ── Validation summary ────────────────────────────────────────────
  - "Every public dataclass in layers.py validates via Pydantic (ADR-005, ADR-032)"
  - "Validation runs on AssetInstance upsert"


# ─────────────────────────────────────────────────────────────────────
# GHERKIN ACCEPTANCE SCENARIOS
# ─────────────────────────────────────────────────────────────────────

gherkin_scenarios: |

  Feature: LayerKind taxonomy and migration
    Scenario: New layer uses LayerKind directly
      Given an AssetDefinition with kind=LayerKind.STRUCTURE
      Then validation succeeds

    Scenario: Legacy LayerType.OBJECT migrates to PROP by default
      When layer_type_to_kind("object") is called
      Then it returns LayerKind.PROP

    Scenario: Legacy LayerType.OBJECT promoted to STRUCTURE on review
      Given a LayerRecord with layer_type="object" and metadata.role="structure"
      When the migration runs
      Then the resulting AssetInstance has definition.kind == LayerKind.STRUCTURE

    Scenario: Unknown LayerType raises
      When layer_type_to_kind("nonsense") is called
      Then ValueError is raised

  Feature: Scene graph attachment via sockets
    Scenario: Child anchored to a parent socket
      Given a registered AssetDefinition "farmhouse_red" with socket "porch"
      And an AssetInstance of "farmhouse_red" on the canvas
      And a CHARACTER AssetInstance with parent_id=<farmhouse instance> and parent_socket="porch"
      When the scene graph is resolved
      Then the character's transform is computed relative to the farmhouse's porch socket

    Scenario: Parent_socket must exist on the parent's definition
      Given a CHARACTER instance with parent_socket="nonsense"
      And a parent definition with sockets (door, porch)
      When validation runs
      Then MissingSocketError is raised

    Scenario: Hand-prop on a character bone
      Given a CHARACTER definition with sockets (hand_l, hand_r, lap)
      And a PROP instance with parent_id=<character>, parent_socket="hand_l"
      Then the prop renders attached to the character's left hand
      And moving the character moves the prop

  Feature: Asset definition / instance split
    Scenario: Same farmhouse appears on three pages
      Given AssetDefinition("farmhouse_red_v1", STRUCTURE) registered
      And three AssetInstance rows each with definition="farmhouse_red_v1"
      When the definition's base_prompt is edited
      Then all three instances are flagged for regeneration on next render

    Scenario: Inline definition for a one-off cloud
      Given an AssetInstance with definition=AssetDefinition(asset_id="", kind=FX, base_prompt="a wispy cloud")
      Then the definition is not added to the registry
      And the instance row carries the embedded definition

    Scenario: Promoting inline to registered is idempotent
      Given an existing registered AssetDefinition with asset_id="farmhouse_red_v1"
      When the agent calls register(<same definition>) again
      Then no error is raised
      And the registry contains exactly one farmhouse_red_v1

  Feature: Asset sheet generation
    Scenario: Generate a character sheet from refs
      Given 4 reference images and a base prompt
      When AssetSheetService.generate_sheet is called
      Then the returned AssetSheet has revision == 1
      And refs == the input refs

    Scenario: Regeneration bumps revision
      Given an existing AssetSheet with revision == 2
      When AssetSheetService.regenerate_sheet is called
      Then the returned sheet has revision == 3
      And sheet_image differs from the previous one

    Scenario: Sheets work for non-character assets
      Given AssetDefinition kind=STRUCTURE with 3 reference photos
      When generate_sheet is called
      Then a multi-angle sheet is produced
      And every page using this asset conditions on the sheet

  Feature: Pose geometry per kind
    Scenario: STRUCTURE accepts FoundationFootprint
      Given AssetDefinition with kind=STRUCTURE and pose_geometry=FoundationFootprint(...)
      Then validation succeeds

    Scenario: STRUCTURE rejects WheelAnchors
      Given AssetDefinition with kind=STRUCTURE and pose_geometry=WheelAnchors(...)
      When validation runs
      Then PoseGeometryMismatchError is raised

    Scenario: PROP rejects all pose_geometry
      Given AssetDefinition with kind=PROP and any pose_geometry
      When validation runs
      Then PoseGeometryMismatchError is raised

  Feature: Occlusion hints
    Scenario: Character in front of tree, behind fence
      Given character instance C, tree T, fence F
      And C.occlusion = OcclusionHint(in_front_of=("T",), behind=("F",))
      When the compositor resolves z-order
      Then F renders in front of C, C renders in front of T

    Scenario: Self-occlusion is invalid
      Given C.occlusion = OcclusionHint(in_front_of=("C",))
      When validation runs
      Then OcclusionCycleError is raised

    Scenario: Two-instance occlusion cycle
      Given A.occlusion.in_front_of=("B",) and B.occlusion.in_front_of=("A",)
      When validation runs
      Then OcclusionCycleError is raised

  Feature: World style composition
    Scenario: Base world style with no overrides
      Given WorldStyle(era="modern", realism="watercolor", ...)
      When merge_world_style(base) is called
      Then the result equals base

    Scenario: Single partial overrides one field
      Given base WorldStyle with realism="watercolor"
      And partial WorldStylePartial(realism="cel")
      When merge_world_style(base, partial) is called
      Then the result has realism="cel" and all other fields from base

    Scenario: Two partials, later wins
      Given partials p1=(realism="cel") and p2=(realism="painterly")
      When merge_world_style(base, p1, p2) is called
      Then the result has realism="painterly"

    Scenario: Empty partial is identity
      When merge_world_style(base, WorldStylePartial()) is called
      Then the result equals base

  Feature: Style volumes for page ranges
    Scenario: Dream sequence pages 7-9 use a different realism
      Given base WorldStyle with realism="cel"
      And StyleVolume(page_range=(7,9), partial_world_style=WorldStylePartial(realism="watercolor"))
      When page 8 is rendered
      Then the prompt is composed with realism="watercolor"

    Scenario: Page outside any volume uses base
      Given the same setup as the dream sequence
      When page 3 is rendered
      Then the prompt is composed with realism="cel"

    Scenario: Overlapping volumes, later overrides
      Given two StyleVolumes both covering page 8
      And v1 sets realism="painterly", v2 sets realism="line"
      When page 8 is rendered
      Then realism="line" wins

  Feature: Personalisation slots → skin binding
    Scenario: Protagonist slot binds to child profile
      Given AssetDefinition("protagonist_template", CHARACTER, skin_set={"protagonist":("tom","sarah","mei")})
      And an AssetInstance with personalization=PersonalizationSlot(kind="child_likeness", binding="protagonist")
      And ChildProfile(name="Sarah")
      When PersonalizationCompiler.compile is called
      Then the instance's skin_binding == {"protagonist": "sarah"}

    Scenario: Unbound slot raises
      Given a PersonalizationSlot whose binding does not match any skin
      When compile is called
      Then SkinBindingError is raised

    Scenario: Accommodations honored on characters
      Given ChildProfile(accommodations=("headphones","fidget"))
      And the protagonist instance
      When compile is called
      Then the prompt for that instance includes the accommodation hints

  Feature: Background composition with ground plane
    Scenario: Other layers anchor against the ground plane
      Given BackgroundComposition with ground_plane.horizon_y=0.62
      And a CHARACTER instance with anchor=GROUND_CONTACT
      When the scene graph resolves placement
      Then the character's feet sit on the horizon line

    Scenario: HORIZON-anchored asset (sun, sailboat)
      Given a STRUCTURE instance with anchor=HORIZON
      Then it renders along the horizon line of the BackgroundComposition

  Feature: Boundary validation
    Scenario: AssetInstance upsert validates the embedded definition
      Given an AssetInstance with an inline definition missing required fields
      When upsert runs
      Then ValidationError is raised

    Scenario: AssetInstance with registry-id definition validates lazily
      Given an AssetInstance with definition="farmhouse_red_v1"
      And the registry contains that asset
      When upsert runs
      Then validation succeeds without expanding the definition


# ─────────────────────────────────────────────────────────────────────
# EDGE CASES
# ─────────────────────────────────────────────────────────────────────

edge_cases:

  - id: ADR039-EC-01
    area: scene-graph
    description: "Deeply nested parent chain (character holds prop holds prop): each level applies its parent's transform; depth >5 logs a warning but is not rejected"

  - id: ADR039-EC-02
    area: scene-graph
    description: "Parent removed mid-edit: children retain parent_id pointing at a missing instance; render raises MissingSocketError before generating"

  - id: ADR039-EC-03
    area: asset-model
    description: "Inline definition with non-empty asset_id is treated as inline; the asset_id is a hint only and does not auto-register"

  - id: ADR039-EC-04
    area: asset-model
    description: "Same asset_id with materially different base_prompt across two registration attempts: second register raises (idempotency check on canonical fields)"

  - id: ADR039-EC-05
    area: asset-sheet
    description: "Sheet with 2 refs (below the 3-5 contract): validation flags as warning, generation proceeds with reduced quality"

  - id: ADR039-EC-06
    area: asset-sheet
    description: "Sheet with 6+ refs: clipped to first 5 with a warning"

  - id: ADR039-EC-07
    area: pose-geometry
    description: "Setting CharacterPose.facial_keypoints on a child too young for face conditioning: kept as data but unused at render time"

  - id: ADR039-EC-08
    area: occlusion
    description: "OcclusionHint references an instance on a different canvas: validation raises (instance not found)"

  - id: ADR039-EC-09
    area: world-style
    description: "WorldStyle.palette_anchors contains a non-hex string: kept as a token name (e.g., 'sage'), interpretation is the renderer's"

  - id: ADR039-EC-10
    area: style-volumes
    description: "page_range with start > end: validation raises ValueError"

  - id: ADR039-EC-11
    area: personalisation
    description: "PersonalizationSlot kind=companion but the profile has no companion: skin defaults to a 'no_companion' variant if defined, else raises SkinBindingError"

  - id: ADR039-EC-12
    area: personalisation
    description: "Slot binding contains characters outside [a-z_], e.g. 'Sarah!': normalised to 'sarah' before lookup"

  - id: ADR039-EC-13
    area: world-style-merge
    description: "merge_world_style with palette_anchors=() (empty tuple) on a partial: treated as 'override to empty', not 'inherit'"

  - id: ADR039-EC-14
    area: background
    description: "BackgroundComposition with all of sky/mid/foreground None: legal (single-image background); ground_plane still required"

  - id: ADR039-EC-15
    area: scene-graph
    description: "Cycle in parent chain (A is parent of B, B is parent of A): validation raises ValueError before MissingSocketError"


# ─────────────────────────────────────────────────────────────────────
# INVARIANTS
# ─────────────────────────────────────────────────────────────────────

invariants:

  - name: layer_kind_total
    description: "Every AssetDefinition has exactly one LayerKind"
    kind: state_invariant
    expression: "definition.kind in {BACKGROUND, STRUCTURE, VEHICLE, PROP, CHARACTER, FX, TEXT}"
    severity: critical

  - name: pose_geometry_matches_kind
    description: "pose_geometry shape matches LayerKind via POSE_GEOMETRY_FOR_KIND, or is None"
    kind: state_invariant
    expression: "definition.pose_geometry is None or type(definition.pose_geometry) == POSE_GEOMETRY_FOR_KIND[definition.kind]"
    severity: critical

  - name: definition_either_registered_or_inline
    description: "AssetInstance.definition is either a string registry id OR an AssetDefinition object"
    kind: state_invariant
    expression: "isinstance(instance.definition, (str, AssetDefinition))"
    severity: critical

  - name: parent_socket_resolves
    description: "Every parent_socket on a child instance names a Socket on the parent's definition"
    kind: precondition
    expression: "parent_socket is None or parent_socket in {s.name for s in parent_definition.sockets}"
    severity: high

  - name: occlusion_dag
    description: "OcclusionHint references on the canvas form a DAG (no cycles, no self-loops)"
    kind: state_invariant
    expression: "no cycle in the occlusion graph"
    severity: critical

  - name: skin_binding_total
    description: "After PersonalizationCompiler.compile, every PersonalizationSlot is bound or has raised"
    kind: postcondition
    expression: "all(instance.skin_binding is not None for instance in compiled if instance.personalization is not None)"
    severity: critical

  - name: world_style_merge_associative
    description: "merge_world_style is associative within a single render; same inputs → same output"
    kind: postcondition
    expression: "merge_world_style(base, p1, p2) == merge_world_style(merge_world_style(base, p1), None, p2)"
    severity: high

  - name: render_is_pure
    description: "A page render is a pure function of (template, child_profile, page_index, world_style, style_volumes, layer_seeds)"
    kind: postcondition
    expression: "render(*inputs) == render(*inputs) for identical inputs"
    severity: critical

  - name: layer_type_alias_round_trips
    description: "layer_type_to_kind is total over the four legacy LayerType values"
    kind: state_invariant
    expression: "layer_type_to_kind(t) defined for t in {BACKGROUND, CHARACTER, OBJECT, TEXT}"
    severity: high

  - name: anchor_vocabulary_minimal
    description: "Anchor enum is exactly {GROUND_CONTACT, HORIZON, FLOATING}"
    kind: state_invariant
    expression: "set(Anchor) == {GROUND_CONTACT, HORIZON, FLOATING}"
    severity: medium
