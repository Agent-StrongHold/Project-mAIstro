"""ADR-044 / #2311 behavioural-parity evidence for the LayerRecord tool RETIRE.

The legacy in-process canvas tool (``maistro_canvas.canvas.tool``, RETIRE per
#2311's ``canvas-legacy-layerrecord`` disposition row, replaced by
``asset_store`` / ``asset_tool`` per ADR-044) exposed a fixed action dispatch
over session-scoped ``Layer`` records. Deleting it required parity evidence
first (ADR-045: "retire legacy/direct route paths only after behavioural
parity … is proven"; #52: "Existing Canvas/Design behavior has parity tests
before lifecycle deletion"). These tests pin that contract as *structure*, not
pixels — golden-image parity belongs to the ADR-044 Phase 2 bridge, which has
not landed and is part of why the remaining LayerRecord surface stays as an
explicitly transitional compatibility window rather than being deleted with
the tool.

The legacy action set below is the contract as verified against the retired
module at deletion time (git history retains the source). Each entry maps a
legacy action to its AssetInstance counterpart on the shipped
:class:`AssetTool` surface; the test fails if any counterpart disappears from
the asset path, so the retirement cannot silently strand a capability.
"""

from __future__ import annotations

from maistro_canvas.canvas.asset_compositor import resolve_occlusion_order
from maistro_canvas.canvas.asset_tool import _VALID_ACTIONS, _deser_instance, _ser_instance
from maistro_canvas.layers import (
    Anchor,
    AssetDefinition,
    AssetInstance,
    LayerKind,
    OcclusionHint,
    Transform,
)

# ─────────────────────────────────────────────────────────────────────
# The retired legacy dispatch surface → AssetInstance counterparts
# ─────────────────────────────────────────────────────────────────────

#: Every action the legacy ``execute_canvas`` dispatched on, mapped to the
#: AssetTool action(s) that cover it. Verified against the retired module at
#: deletion time; the mapping is the parity contract, not an inference.
LEGACY_ACTION_TO_ASSET_COUNTERPART: dict[str, tuple[str, ...]] = {
    # generate → sheet generation over a definition (image variants land on
    # the sheet / render plan instead of ad-hoc layer rows).
    "generate": ("generate_sheet", "render_page"),
    # refine → regeneration anchored on the existing sheet (refs conditioning).
    "refine": ("regenerate_sheet",),
    # reference → multi-view reference sets are the sheet's refs.
    "reference": ("generate_sheet", "regenerate_sheet"),
    # composite → the render plan + page render is the composited output.
    "composite": ("plan", "render_page"),
    # text → a TEXT-kind inline definition (ADR-044 bridge contract: the text
    # is rendered into the prompt for the compositor's text path).
    "text": ("register_definition", "upsert_instance"),
    # upload → an instance whose history[0] is the uploaded image (ADR-044
    # bridge contract: image bytes become history plus an inline definition).
    "upload": ("upsert_instance",),
    "list_layers": ("list_instances",),
    # transform → the instance transform (tx/ty/sx/sy/rotation).
    "transform": ("upsert_instance",),
    "delete": ("remove_instance",),
    # duplicate → a new instance of the same definition.
    "duplicate": ("upsert_instance",),
}

#: The tier→model counterpart: the legacy tool fell back to DRAFT_MODELS /
#: PROOF_MODELS priority lists; the asset path's fallback is the executor's
#: ``default_model_id`` (the deployment's draft model), pinned here so the
#: fallback shape — one explicit deployment default, not a hardcoded list —
#: stays part of the parity record.
TIER_COUNTERPART = "AssetExecutor.default_model_id"


def test_every_legacy_action_has_a_live_asset_counterpart() -> None:
    """The retirement cannot strand a legacy capability: each mapped
    counterpart must still be a dispatchable AssetTool action."""
    assert LEGACY_ACTION_TO_ASSET_COUNTERPART, "parity mapping must not be empty"
    for legacy_action, counterparts in LEGACY_ACTION_TO_ASSET_COUNTERPART.items():
        for counterpart in counterparts:
            assert counterpart in _VALID_ACTIONS, (
                f"legacy action {legacy_action!r} lost its AssetInstance counterpart "
                f"{counterpart!r}"
            )


def test_asset_surface_covers_the_full_legacy_dispatch_set() -> None:
    """The mapping is total over the retired dispatch surface: ten legacy
    actions, each with at least one counterpart — no legacy capability is
    silently dropped from the parity record."""
    assert len(LEGACY_ACTION_TO_ASSET_COUNTERPART) == 10
    assert all(counterparts for counterparts in LEGACY_ACTION_TO_ASSET_COUNTERPART.values())


def test_tier_model_fallback_counterpart_exists() -> None:
    """The legacy DRAFT/PROOF model-list fallback has an explicit counterpart
    shape on the asset path (the executor's deployment-supplied default)."""
    from maistro_canvas.canvas.asset_executor import AssetExecutor

    assert "default_model_id" in AssetExecutor.__init__.__code__.co_varnames


# ─────────────────────────────────────────────────────────────────────
# Invariant 1 — back-to-front z ordering (legacy ``sorted_layers``)
# ─────────────────────────────────────────────────────────────────────


def _instance(instance_id: str, z_index: int) -> AssetInstance:
    return AssetInstance(
        instance_id=instance_id,
        canvas_id="c1",
        definition=AssetDefinition(
            asset_id=f"def-{instance_id}", kind=LayerKind.PROP, base_prompt="p"
        ),
        transform=Transform(),
        z_index=z_index,
    )


def test_occlusion_order_is_back_to_front_by_z_index() -> None:
    """Legacy ``Canvas.sorted_layers()`` returned layers back-to-front by
    ``z_index`` (stable sort). The asset path's ordering must reproduce that
    ordering when no occlusion hints constrain it."""
    instances = [
        _instance("i-0", 0),
        _instance("i-10", 10),
        _instance("i-20a", 20),
        _instance("i-20b", 20),
        _instance("i-30", 30),
    ]
    ordered = resolve_occlusion_order(instances)
    assert [i.instance_id for i in ordered] == ["i-0", "i-10", "i-20a", "i-20b", "i-30"]


def test_occlusion_order_ties_break_on_input_order() -> None:
    """Legacy ``sorted`` was stable: equal z_index kept insertion order. The
    asset ordering's tie-break (z_index ASC, then input order) matches."""
    instances = [_instance(name, 5) for name in ("first", "second", "third")]
    ordered = resolve_occlusion_order(instances)
    assert [i.instance_id for i in ordered] == ["first", "second", "third"]


def test_occlusion_order_respects_in_front_of_constraints() -> None:
    """The asset path's superset guarantee: explicit occlusion edges are
    honoured on top of the z ordering the legacy path expressed only
    implicitly through z_index."""
    behind = _instance("ground", 0)
    in_front = _instance("prop", 100)
    in_front.occlusion = OcclusionHint(in_front_of=("ground",), behind=())
    ordered = resolve_occlusion_order([in_front, behind])
    assert [i.instance_id for i in ordered] == ["ground", "prop"]


def test_store_listing_is_z_ordered_like_the_legacy_surface() -> None:
    """The store-level listing the asset HTTP surface serves is z_index ASC —
    the same back-to-front order the legacy layer listing guaranteed."""
    import asyncio

    from maistro_canvas.canvas.asset_store import InMemoryAssetStore

    async def run() -> list[str]:
        store = InMemoryAssetStore()
        for z in (30, 10, 20):
            await store.upsert_instance(_instance(f"i{z}", z), org_id="org")
        return [i.instance_id for i in await store.list_instances("c1", org_id="org")]

    assert asyncio.run(run()) == ["i10", "i20", "i30"]


# ─────────────────────────────────────────────────────────────────────
# Invariant 2 — append-only version history (frontend SPEC)
# ─────────────────────────────────────────────────────────────────────


def test_instance_history_survives_serialisation_in_order() -> None:
    """The frontend SPEC invariant ("Once an image appears in a layer, it is
    never overwritten without being pushed to history[]") is carried on the
    asset path by ``AssetInstance.history``. The wire round-trip must preserve
    every entry and its order — a dropped or reordered entry would silently
    rewrite a layer's version history."""
    instance = _instance("i1", 0)
    instance.history = ("blob://v1", "blob://v2", "blob://v3")
    round_tripped = _deser_instance(_ser_instance(instance))
    assert round_tripped.history == ("blob://v1", "blob://v2", "blob://v3")


def test_sheet_regeneration_bumps_revision_not_rewrites() -> None:
    """The legacy tool's refine produced a new variant rather than overwriting
    the accepted one. The asset counterpart is the sheet revision counter:
    regeneration must advance the revision, never reset it."""
    import asyncio

    from maistro_canvas.canvas.asset_executor import AssetExecutor
    from maistro_canvas.canvas.asset_store import InMemoryAssetStore

    class _StubGen:
        async def generate(self, **_kwargs: object) -> list[object]:
            class _Img:
                url = "blob://sheet-1"

            return [_Img()]

    async def run() -> tuple[int, int]:
        store = InMemoryAssetStore()
        await store.register_definition(
            AssetDefinition(asset_id="a1", kind=LayerKind.CHARACTER, base_prompt="hero"),
            org_id="org",
        )
        executor = AssetExecutor(store, _StubGen(), org_id="org")
        first = await executor.generate_sheet(asset_id="a1", refs=(), prompt="hero")
        second = await executor.regenerate_sheet(asset_id="a1", prompt="hero, side view")
        return first.revision, second.revision

    first_revision, second_revision = asyncio.run(run())
    assert first_revision == 1
    assert second_revision == 2


# ─────────────────────────────────────────────────────────────────────
# Invariant 3 — the TEXT path stays a first-class kind (legacy text layers)
# ─────────────────────────────────────────────────────────────────────


def test_text_kind_survives_definition_round_trip() -> None:
    """Legacy text layers (``layer_type='text'``) map to TEXT-kind inline
    definitions per the ADR-044 bridge contract. The kind must remain
    representable on the asset surface the tool retirement leans on."""
    text_defn = AssetDefinition(
        asset_id="caption",
        kind=LayerKind.TEXT,
        base_prompt="Once upon a time",
    )
    instance = AssetInstance(
        instance_id="t1",
        canvas_id="c1",
        definition=text_defn,
        transform=Transform(),
        anchor=Anchor.FLOATING,
        z_index=50,
    )
    round_tripped = _deser_instance(_ser_instance(instance))
    assert isinstance(round_tripped.definition, AssetDefinition)
    assert round_tripped.definition.kind is LayerKind.TEXT
    assert round_tripped.anchor is Anchor.FLOATING
