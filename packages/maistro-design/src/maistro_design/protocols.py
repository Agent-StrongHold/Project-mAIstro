"""maistro-design protocols — structural interfaces for DI."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from maistro_design.types import (
        DesignProject,
        DesignSkill,
        DesignSystem,
        DiscoveryResult,
        RenderSlot,
        TypographyToken,
    )


@runtime_checkable
class DesignSkillRegistry(Protocol):
    def register(self, skill: DesignSkill) -> None: ...
    def get(self, slug: str) -> DesignSkill | None: ...
    def list_all(self) -> list[DesignSkill]: ...
    def list_by_mode(self, mode: str) -> list[DesignSkill]: ...
    def list_featured(self) -> list[DesignSkill]: ...
    def list_available(self, filled_slots: frozenset[RenderSlot]) -> list[DesignSkill]: ...
    def delete(self, slug: str) -> bool: ...


@runtime_checkable
class DesignSystemRegistry(Protocol):
    def register(self, system: DesignSystem) -> None: ...
    def get(self, slug: str) -> DesignSystem | None: ...
    def list_all(self) -> list[DesignSystem]: ...
    def delete(self, slug: str) -> bool: ...


@runtime_checkable
class DesignProjectStore(Protocol):
    """Every single-project operation takes the caller's scope.

    `org_id` is keyword-only and has no default on all three. The two list
    methods always took it; `get`, `update` and `delete` matched on id alone, so
    one authenticated caller could read, edit or delete another scope's project.
    A default here is a default the next caller omits, which is the shape of the
    defect this closes (#326).
    """

    async def create(self, project: DesignProject) -> DesignProject: ...
    async def get(self, project_id: str, *, org_id: str) -> DesignProject | None: ...
    async def list_by_skill(self, skill_slug: str, org_id: str) -> list[DesignProject]: ...
    async def list_by_org(self, org_id: str) -> list[DesignProject]: ...
    async def update(self, project: DesignProject) -> DesignProject: ...
    async def delete(self, project_id: str, *, org_id: str) -> None: ...


@runtime_checkable
class DesignEngineProtocol(Protocol):
    async def run_discovery(self, skill_slug: str) -> list[dict[str, Any]]: ...
    async def generate(self, discovery: DiscoveryResult) -> DesignProject: ...


@runtime_checkable
class HTMLRenderer(Protocol):
    """Rasterizes assembled HTML(+CSS) into a binary image/document format."""

    async def render(self, html: str, *, css: str = "", fmt: Literal["png", "pdf"]) -> bytes: ...


@runtime_checkable
class SVGRenderer(Protocol):
    """Rasterizes SVG markup into a binary image/document format."""

    async def render(self, svg: str, *, fmt: Literal["png", "pdf"]) -> bytes: ...


@runtime_checkable
class TypographyRenderer(Protocol):
    """Renders a run of text in a given typeface to a binary raster."""

    async def render_text(self, text: str, *, token: TypographyToken) -> bytes: ...
