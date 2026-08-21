"""Canvas Studio protocols — structural interfaces for DI.

All canvas-related business logic depends only on these protocols.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from maistro_canvas.layers import (
        AssetDefinition,
        AssetInstance,
        AssetSheet,
        ChildProfile,
        RenderStyle,
        WorldStyle,
    )
    from maistro_canvas.types import (
        CanvasRecord,
        CompositeResult,
        GenerationJobRecord,
        LayerRecord,
        ModelInfo,
    )


@runtime_checkable
class CanvasStore(Protocol):
    """CRUD for canvases, layers, generation jobs, and composites."""

    async def create_canvas(
        self,
        *,
        name: str,
        width: int,
        height: int,
        background_color: str = "#FFFFFF",
        org_id: str = "",
    ) -> CanvasRecord: ...

    async def get_canvas(self, canvas_id: str) -> CanvasRecord | None: ...

    async def list_canvases(
        self,
        org_id: str,
        *,
        include_archived: bool = False,
    ) -> list[CanvasRecord]: ...

    async def update_canvas(self, canvas: CanvasRecord) -> CanvasRecord: ...

    async def add_layer(
        self,
        canvas_id: str,
        *,
        name: str,
        layer_type: str,
        z_index: int | None = None,
        **kwargs: Any,
    ) -> LayerRecord: ...

    async def get_layer(self, layer_id: str) -> LayerRecord | None: ...

    async def list_layers(self, canvas_id: str) -> list[LayerRecord]: ...

    async def update_layer(self, layer: LayerRecord) -> LayerRecord: ...

    async def remove_layer(self, layer_id: str) -> None: ...

    async def reorder_layers(
        self,
        canvas_id: str,
        assignments: list[dict[str, Any]],
    ) -> list[LayerRecord]: ...

    async def create_job(self, job: GenerationJobRecord) -> GenerationJobRecord: ...

    async def get_job(self, job_id: str) -> GenerationJobRecord | None: ...

    async def update_job(self, job: GenerationJobRecord) -> GenerationJobRecord: ...

    async def active_job_for_layer(self, layer_id: str) -> GenerationJobRecord | None: ...

    async def list_jobs_for_layer(self, layer_id: str) -> list[GenerationJobRecord]: ...

    async def save_composite(self, result: CompositeResult) -> CompositeResult: ...

    async def latest_composite(self, canvas_id: str) -> CompositeResult | None: ...

    async def store_blob(
        self,
        data: bytes,
        *,
        format: str,
        metadata: dict[str, Any] | None = None,
    ) -> str: ...


@runtime_checkable
class ImageGenClient(Protocol):
    """Calls an image-generation backend (LiteLLM proxy or local P40 server).

    Per ADR-039 §9, `generate` accepts optional conditioning args
    (`world_style`, `render_style`, `asset_sheet`) that the backend
    folds into the prompt or routes to the appropriate adapter
    (IP-Adapter / FaceID / ControlNet etc.). Backends that don't
    support a given conditioning ignore it.
    """

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

    async def refine(
        self,
        *,
        model_id: str,
        source_url: str,
        prompt: str,
        region: str = "full",
        strength: float = 0.6,
    ) -> ImageData: ...

    async def list_image_models(self) -> list[ModelInfo]: ...


@runtime_checkable
class CompositorService(Protocol):
    """Assembles layer images into a single composited image."""

    async def composite(
        self,
        canvas: CanvasRecord,
        layers: list[LayerRecord],
    ) -> CompositeResult: ...


@runtime_checkable
class AssetSheetService(Protocol):
    """Generates and stores reference sheets for named assets (ADR-039 §4).

    A sheet is created from 3-5 reference images and used as
    conditioning for every generation that references the asset.
    Generalised from the original character-only workflow.
    """

    async def generate_sheet(
        self,
        *,
        asset_id: str,
        refs: tuple[str, ...],
        prompt: str,
        params: dict[str, Any] | None = None,
    ) -> AssetSheet: ...

    async def get_sheet(self, asset_id: str) -> AssetSheet | None: ...

    async def regenerate_sheet(self, asset_id: str) -> AssetSheet: ...


@runtime_checkable
class AssetRegistry(Protocol):
    """Stores named, reusable AssetDefinitions (ADR-039 §3).

    Inline (anonymous) definitions live inside `AssetInstance.definition`
    and never touch this registry. The agent (davinci) may promote an
    inline definition to a registered one when reuse is detected; this
    promotion is idempotent.
    """

    async def register(self, definition: AssetDefinition) -> AssetDefinition: ...

    async def get(self, asset_id: str) -> AssetDefinition | None: ...

    async def list_by_kind(self, kind: str) -> list[AssetDefinition]: ...

    async def update(self, definition: AssetDefinition) -> AssetDefinition: ...


@runtime_checkable
class PersonalizationCompiler(Protocol):
    """Compiles PersonalizationSlot intent into skin_binding (ADR-039 §5).

    At render time, walks the scene graph, finds every `AssetInstance`
    with a `personalization` slot, looks up the matching value in the
    `ChildProfile`, and writes a `skin_binding` onto the instance for
    the compositor to consume.
    """

    def compile(
        self,
        *,
        instances: list[AssetInstance],
        profile: ChildProfile,
    ) -> list[AssetInstance]: ...


class ImageData:
    """Raw image data returned by the generation backend."""

    __slots__ = ("bytes_", "height", "url", "width")

    def __init__(
        self,
        *,
        width: int,
        height: int,
        url: str = "",
        bytes_: bytes = b"",
    ) -> None:
        self.width = width
        self.height = height
        self.url = url
        self.bytes_ = bytes_
