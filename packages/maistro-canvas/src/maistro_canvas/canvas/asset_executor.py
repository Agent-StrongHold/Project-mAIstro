"""Canvas asset executor — coordinates the asset store, compositor,
and image-generation backend behind a friendly façade for agents and
HTTP routes. Per ADR-043.

The executor is pure-python and testable without a network or PIL.
Image generation is mocked through the ``ImageGenClient`` protocol;
tests inject a fake client that returns synthetic ``ImageData``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Protocol

from maistro_canvas.canvas.asset_compositor import (
    PlannedRender,
    RenderPlan,
    plan_render,
)
from maistro_canvas.canvas.asset_store import Book
from maistro_canvas.layers import (
    AssetDefinition,
    AssetInstance,
    AssetSheet,
    ChildProfile,
    RenderStyle,
    StyleVolume,
    WorldStyle,
)

if TYPE_CHECKING:
    from maistro_canvas.protocols import ImageData


class _AssetStore(Protocol):
    """Structural protocol covering the methods the executor calls.
    InMemoryAssetStore and PostgresAssetStore both satisfy it."""

    async def register_definition(self, defn: AssetDefinition) -> AssetDefinition: ...
    async def get_definition(self, asset_id: str) -> AssetDefinition | None: ...
    async def list_definitions_by_kind(self, kind: str) -> list[AssetDefinition]: ...
    async def update_definition(self, defn: AssetDefinition) -> AssetDefinition: ...
    async def upsert_sheet(self, sheet: AssetSheet) -> AssetSheet: ...
    async def get_sheet(self, asset_id: str) -> AssetSheet | None: ...
    async def regenerate_sheet(
        self,
        asset_id: str,
        sheet_image: str,
        refs: tuple[str, ...] | None = None,
        params: dict[str, Any] | None = None,
    ) -> AssetSheet: ...
    async def upsert_instance(self, instance: AssetInstance) -> AssetInstance: ...
    async def get_instance(self, instance_id: str) -> AssetInstance | None: ...
    async def list_instances(self, canvas_id: str) -> list[AssetInstance]: ...
    async def remove_instance(self, instance_id: str) -> None: ...
    async def upsert_profile(self, profile: ChildProfile) -> ChildProfile: ...
    async def get_profile(self, profile_id: str) -> ChildProfile | None: ...
    async def get_book(self, book_id: str) -> Book | None: ...
    async def update_book(self, book: Book) -> Book: ...


class _ImageGenClient(Protocol):
    """Subset of ``maistro_canvas.protocols.ImageGenClient`` the
    executor calls. Defined locally to keep the import graph small."""

    async def generate(
        self,
        *,
        model_id: str,
        prompt: str,
        width: int,
        height: int,
        count: int = 1,
        seed: int | None = None,
        negative_prompt: str = "",
        world_style: WorldStyle | None = None,
        render_style: RenderStyle | None = None,
        asset_sheet: AssetSheet | None = None,
    ) -> list[ImageData]: ...


class AssetExecutor:
    """Action coordinator for the ADR-039 canvas asset model.

    Used by:
      - the FastAPI router (ADR-042) — directly via DI
      - the agent tool (ADR-043 §AssetTool) — through dispatch
    """

    def __init__(
        self,
        store: _AssetStore,
        image_gen: _ImageGenClient,
        *,
        sheet_size: tuple[int, int] = (1024, 1024),
        default_model_id: str = "default",
    ) -> None:
        self._store = store
        self._gen = image_gen
        self._sheet_size = sheet_size
        self._default_model_id = default_model_id

    # ── Definition / instance pass-through ─────────────────────────

    async def register_definition(self, defn: AssetDefinition) -> AssetDefinition:
        return await self._store.register_definition(defn)

    async def get_definition(self, asset_id: str) -> AssetDefinition | None:
        return await self._store.get_definition(asset_id)

    async def list_definitions_by_kind(self, kind: str) -> list[AssetDefinition]:
        return await self._store.list_definitions_by_kind(kind)

    async def upsert_instance(self, instance: AssetInstance) -> AssetInstance:
        return await self._store.upsert_instance(instance)

    async def list_instances(self, canvas_id: str) -> list[AssetInstance]:
        return await self._store.list_instances(canvas_id)

    async def remove_instance(self, instance_id: str) -> None:
        await self._store.remove_instance(instance_id)

    # ── Sheet generation ───────────────────────────────────────────

    async def generate_sheet(
        self,
        *,
        asset_id: str,
        refs: tuple[str, ...],
        prompt: str,
        params: dict[str, Any] | None = None,
    ) -> AssetSheet:
        """Create a new AssetSheet for an asset_id.

        Calls the image backend with the refs as conditioning. The
        backend returns one image; we persist it as the sheet's
        ``sheet_image`` and return the row.
        """
        defn = await self._store.get_definition(asset_id)
        existing = defn.asset_sheet if defn is not None else None
        # Use the existing sheet (if any) as conditioning so successive
        # regenerations stay anchored.
        images = await self._gen.generate(
            model_id=self._default_model_id,
            prompt=prompt,
            width=self._sheet_size[0],
            height=self._sheet_size[1],
            count=1,
            asset_sheet=existing,
        )
        if not images:
            msg = "ImageGenClient returned no images for sheet generation"
            raise RuntimeError(msg)
        sheet_image = _image_to_url(images[0])
        new_sheet = AssetSheet(
            asset_id=asset_id,
            refs=refs,
            sheet_image=sheet_image,
            revision=(existing.revision + 1) if existing is not None else 1,
            generation_params=dict(params or {}),
        )
        return await self._store.upsert_sheet(new_sheet)

    async def regenerate_sheet(
        self,
        *,
        asset_id: str,
        prompt: str,
        refs: tuple[str, ...] | None = None,
        params: dict[str, Any] | None = None,
    ) -> AssetSheet:
        """Bump the revision of an existing sheet."""
        existing = await self._store.get_sheet(asset_id)
        images = await self._gen.generate(
            model_id=self._default_model_id,
            prompt=prompt,
            width=self._sheet_size[0],
            height=self._sheet_size[1],
            count=1,
            asset_sheet=existing,
        )
        if not images:
            msg = "ImageGenClient returned no images for sheet regeneration"
            raise RuntimeError(msg)
        return await self._store.regenerate_sheet(
            asset_id,
            sheet_image=_image_to_url(images[0]),
            refs=refs,
            params=params,
        )

    # ── Render plan ────────────────────────────────────────────────

    async def plan(
        self,
        *,
        canvas_id: str,
        world_style: WorldStyle,
        style_volumes: Sequence[StyleVolume] = (),
        page_index: int | None = None,
        render_style: RenderStyle | None = None,
        profile_id: str | None = None,
    ) -> RenderPlan:
        """Build the render plan for a canvas.

        Pulls all instances on the canvas, pre-loads any registered
        definitions referenced by string id, and runs ``plan_render``
        from ADR-041.
        """
        instances = await self._store.list_instances(canvas_id)
        profile = await self._store.get_profile(profile_id) if profile_id is not None else None

        referenced_ids = {i.definition for i in instances if isinstance(i.definition, str)}
        preloaded: dict[str, AssetDefinition | None] = {}
        for aid in referenced_ids:
            preloaded[aid] = await self._store.get_definition(aid)

        def lookup(asset_id: str) -> AssetDefinition | None:
            return preloaded.get(asset_id)

        return plan_render(
            canvas_id=canvas_id,
            instances=instances,
            world_style=world_style,
            style_volumes=tuple(style_volumes),
            page_index=page_index,
            render_style=render_style,
            profile=profile,
            registry_lookup=lookup,
        )

    # ── Page rendering ─────────────────────────────────────────────

    async def render_page(
        self,
        *,
        canvas_id: str,
        plan: RenderPlan,
        size: tuple[int, int] = (1024, 1024),
    ) -> list[tuple[PlannedRender, list[ImageData]]]:
        """Render every PlannedRender via ``ImageGenClient.generate``.

        Sequential — one call per layer, in plan order. Returns a
        parallel list so the agent can pick / retry per layer.
        Persistence of choices (e.g. saving image_url back onto an
        AssetInstance) is the agent's responsibility; this method is
        side-effect-free on the store.
        """
        out: list[tuple[PlannedRender, list[ImageData]]] = []
        for planned in plan.rendered:
            images = await self._gen.generate(
                model_id=self._default_model_id,
                prompt=planned.prompt,
                width=size[0],
                height=size[1],
                count=1,
                world_style=plan.world_style,
                # The asset_sheet conditioning lives on the planner output.
                asset_sheet=AssetSheet(
                    asset_id="",
                    refs=(),
                    sheet_image=planned.asset_sheet_ref,
                    revision=0,
                )
                if planned.asset_sheet_ref is not None
                else None,
            )
            out.append((planned, images))
        return out


def _image_to_url(image: ImageData) -> str:
    """Coerce an ImageData into a string URL/path suitable for storage.

    Prefers the ``url`` if set; falls back to a ``bytes_:<bytes>`` placeholder
    when the backend returned raw bytes (the persistence layer can choose
    to upload + replace the placeholder later).
    """
    if image.url:
        return image.url
    if image.bytes_:
        # Tests typically inject a synthetic URL here; production
        # backends always return one.
        return f"bytes:{len(image.bytes_)}"
    msg = "ImageData has neither url nor bytes_"
    raise ValueError(msg)


__all__ = ["AssetExecutor"]
