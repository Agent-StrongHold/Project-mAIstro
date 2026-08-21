"""DesignEngine — discovery form → Warden scan → trust assignment → prompt stack.

The engine builds the prompt stack and creates artifacts but does NOT call an LLM.
The caller passes the assembled output to maistro-core's conduit (ADR-019 / ADR-061).

Trust contamination: context_trust_tier is monotonically decreasing per instance.
One engine instance per session; callers manage session lifecycle.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from maistro_design.scan import scan_design_output
from maistro_design.trust import (
    InMemoryTrustBanishList,
    InMemoryTrustReviewQueue,
    TrustTier,
    scan_and_record,
)
from maistro_design.types import (
    ArtifactKind,
    ArtifactNode,
    DesignOutput,
    DesignProject,
    DesignSystemNotFoundError,
    DiscoveryIncompleteError,
    DiscoveryResult,
    IncompatibleDesignSystemError,
    OutputFormat,
    SkillMode,
    SkillModeError,
    SkillNotFoundError,
    TrustBannedError,
)

if TYPE_CHECKING:
    from maistro_canvas.protocols import CanvasStore, ImageGenClient
    from maistro_design.protocols import (
        DesignProjectStore,
        DesignSkillRegistry,
        DesignSystemRegistry,
        HTMLRenderer,
        SVGRenderer,
        TypographyRenderer,
    )


_RENDERER_ATTRS: dict[str, str] = {
    "html": "_html_renderer",
    "svg": "_svg_renderer",
    "typography": "_typography_renderer",
}


def _scan_output_or_raise(output: DesignOutput, banish_list: InMemoryTrustBanishList) -> None:
    report = scan_design_output(output, banish_list=banish_list)
    if not report.passed:
        msg = f"Generated output failed the output scan: {report.blocking_flags}"
        raise TrustBannedError(msg)


def _build_output(prompt_stack: str, trust_tier: TrustTier) -> DesignOutput:
    return DesignOutput(
        root=ArtifactNode(
            key="prompt-stack",
            kind=ArtifactKind.FILE,
            format=OutputFormat.MARKDOWN,
            value=prompt_stack,
        ),
        trust_tier=trust_tier,
    )


_BINARY_FORMATS = frozenset({OutputFormat.PNG, OutputFormat.PDF, OutputFormat.PPTX})


def _artifact_leaf(fmt: OutputFormat, content: str | bytes) -> ArtifactNode:
    """Classify by format, not by content's Python type.

    A text format (HTML/CSS/JS/SVG/JSON/MARKDOWN) handed to us as UTF-8 bytes
    must still become a FILE leaf — scan_design_output() skips BLOB leaves
    entirely, so classifying by isinstance(content, bytes) would let a
    byte-encoded <script> payload bypass the Warden scan build_multimodal_output()
    otherwise guarantees.
    """
    if fmt in _BINARY_FORMATS:
        return ArtifactNode(key=fmt.value, kind=ArtifactKind.BLOB, format=fmt, value=content)
    text_value = content.decode("utf-8") if isinstance(content, bytes) else content
    return ArtifactNode(key=fmt.value, kind=ArtifactKind.FILE, format=fmt, value=text_value)


def build_multimodal_output(
    contents: dict[OutputFormat, str | bytes],
    *,
    trust_tier: TrustTier,
    banish_list: InMemoryTrustBanishList | None = None,
) -> DesignOutput:
    """Assemble a hierarchical DesignOutput from content a caller already produced.

    generate() never calls an LLM or an image-gen backend (ADR-061), so it has no
    real per-format content to assemble. Callers invoke this *after* their own
    LLM/image-gen step — e.g. from maistro-core's conduit once it has a response
    for each of a skill's declared output_formats.

    One entry produces a single FILE (str) or BLOB (bytes) root, matching
    generate()'s single-artifact shape. Multiple entries produce a CONTAINER
    root with one FILE/BLOB child per format, keyed by OutputFormat.value
    (e.g. "html", "css", "png") since no real filenames exist pre-render.

    Runs scan_design_output() before returning; raises TrustBannedError if a
    blocking pattern is found, same as generate().
    """
    if not contents:
        msg = "build_multimodal_output() requires at least one (format, content) entry"
        raise ValueError(msg)

    if len(contents) == 1:
        ((fmt, content),) = contents.items()
        root = _artifact_leaf(fmt, content)
    else:
        children = {fmt.value: _artifact_leaf(fmt, content) for fmt, content in contents.items()}
        root = ArtifactNode(key="output", kind=ArtifactKind.CONTAINER, children=children)

    output = DesignOutput(root=root, trust_tier=trust_tier)
    _scan_output_or_raise(
        output, banish_list if banish_list is not None else InMemoryTrustBanishList()
    )
    return output


async def persist_blobs(output: DesignOutput, canvas_store: CanvasStore) -> dict[str, str]:
    """Persist every BLOB leaf in output via canvas_store.store_blob().

    Returns {dotted_address: stored_id} for each BLOB leaf. Does not mutate
    output — outputs are immutable once created (ADR-062326-702b).
    """
    stored: dict[str, str] = {}
    for address, node in output.root.walk():
        if node.kind is not ArtifactKind.BLOB:
            continue
        stored[address] = await canvas_store.store_blob(
            node.value,  # type: ignore[arg-type]  # BLOB leaves always carry bytes
            format=node.format.value if node.format else "",
            metadata=node.metadata,
        )
    return stored


class DesignEngine:
    """Orchestrates skill → discovery → Warden scan → prompt stack → canvas/A2A.

    One instance per session. context_trust_tier is monotonically decreasing.
    """

    def __init__(
        self,
        skill_registry: DesignSkillRegistry,
        system_registry: DesignSystemRegistry,
        banish_list: InMemoryTrustBanishList | None = None,
        trust_review_queue: InMemoryTrustReviewQueue | None = None,
        canvas_store: CanvasStore | None = None,
        image_gen: ImageGenClient | None = None,
        html_renderer: HTMLRenderer | None = None,
        svg_renderer: SVGRenderer | None = None,
        typography_renderer: TypographyRenderer | None = None,
        project_store: DesignProjectStore | None = None,
    ) -> None:
        self._skills = skill_registry
        self._systems = system_registry
        self._banish_list = banish_list if banish_list is not None else InMemoryTrustBanishList()
        self._trust_review_queue = (
            trust_review_queue if trust_review_queue is not None else InMemoryTrustReviewQueue()
        )
        self._canvas_store = canvas_store
        self._image_gen = image_gen
        self._html_renderer = html_renderer
        self._svg_renderer = svg_renderer
        self._typography_renderer = typography_renderer
        self._project_store = project_store
        self._context_trust_tier: TrustTier = TrustTier.T0

    @property
    def context_trust_tier(self) -> TrustTier:
        return self._context_trust_tier

    def _contaminate(self, tier: TrustTier) -> None:
        self._context_trust_tier = self._context_trust_tier.min(tier)

    def reset_context(self) -> None:
        """Reset trust context to T0 (trusted).

        Call before each generate() to prevent trust contamination across requests.
        """
        self._context_trust_tier = TrustTier.T0

    def _check_compatibility(self, skill: Any, design_system_slug: str) -> None:
        if (
            skill.compatible_design_systems
            and design_system_slug not in skill.compatible_design_systems
        ):
            msg = (
                f"Skill '{skill.slug}' is not compatible with design system "
                f"'{design_system_slug}'. "
                f"Compatible: {skill.compatible_design_systems}"
            )
            raise IncompatibleDesignSystemError(msg)

    def _check_image_gen(self, skill: Any) -> None:
        if skill.mode == SkillMode.IMAGE and self._image_gen is None:
            msg = (
                f"Skill '{skill.slug}' requires an image generation client "
                f"(mode={skill.mode}) but none was provided to DesignEngine."
            )
            raise SkillModeError(msg)

    def _check_renderer_available(self, skill: Any) -> None:
        if skill.required_renderer is None:
            return
        attr_name = _RENDERER_ATTRS[skill.required_renderer]
        if getattr(self, attr_name) is None:
            msg = (
                f"Skill '{skill.slug}' requires a '{skill.required_renderer}' renderer "
                f"but none was provided to DesignEngine."
            )
            raise SkillModeError(msg)

    def _scan_discovery_responses(self, discovery: DiscoveryResult) -> None:
        for key, value in discovery.responses.items():
            if self._banish_list.is_banned(value):
                msg = f"Discovery response for field '{key}' matches a banished pattern"
                raise TrustBannedError(msg)
            response_tier = scan_and_record(
                value,
                source="discovery_field",
                source_key=key,
                record_id=str(uuid.uuid4()),
                banish_list=self._banish_list,
                review_queue=self._trust_review_queue,
            )
            self._contaminate(response_tier)

    def _validate_required_fields(self, skill: Any, discovery: DiscoveryResult) -> None:
        for field in skill.discovery_form:
            if field.required and field.key not in discovery.responses:
                msg = (
                    f"Required discovery field '{field.key}' ('{field.label}') "
                    f"is missing for skill '{skill.slug}'"
                )
                raise DiscoveryIncompleteError(msg)

    def _build_prompt_stack(self, skill: Any, system: Any, discovery: DiscoveryResult) -> str:
        parts: list[str] = []
        if skill.system_prompt:
            parts.append(f"## Skill Instructions\n{skill.system_prompt}")
        if system.design_md:
            parts.append(f"## Design System: {system.name}\n{system.design_md}")
        elif system.tokens_css:
            parts.append(f"## Design Tokens ({system.name})\n```css\n{system.tokens_css}\n```")
        if discovery.responses:
            response_lines = "\n".join(f"- **{k}**: {v}" for k, v in discovery.responses.items())
            parts.append(f"## Discovery Responses\n{response_lines}")
        return "\n\n".join(parts)

    async def run_discovery(self, skill_slug: str) -> list[dict[str, Any]]:
        """Return the skill's discovery form as a list of serialisable dicts.

        Raises SkillNotFoundError for unknown slugs.
        """
        skill = self._skills.get(skill_slug)
        if skill is None:
            msg = f"Design skill '{skill_slug}' not found"
            raise SkillNotFoundError(msg)
        return [f.to_dict() for f in skill.discovery_form]

    async def generate(
        self, discovery: DiscoveryResult, org_id: str = "default-org", team_id: str | None = None
    ) -> DesignProject:
        """Build a DesignProject from completed discovery responses.

        Pipeline:
          1. Reset trust context to T0 (prevent cross-request contamination)
          2. Resolve skill + design system; check compatibility, image_gen, and renderers
          3. Contaminate context with skill + system + discovery trust tiers
          4. Scan discovery responses through banish list and Warden
          5. Validate required discovery fields
          6. Assemble prompt stack and optionally create a CanvasRecord
          7. Persist project via project_store if available
        """
        self.reset_context()
        skill = self._skills.get(discovery.skill_slug)
        if skill is None:
            msg = f"Design skill '{discovery.skill_slug}' not found"
            raise SkillNotFoundError(msg)

        system = self._systems.get(discovery.design_system_slug)
        if system is None:
            msg = f"Design system '{discovery.design_system_slug}' not found"
            raise DesignSystemNotFoundError(msg)

        self._check_compatibility(skill, discovery.design_system_slug)
        self._check_image_gen(skill)
        self._check_renderer_available(skill)

        self._contaminate(skill.trust_tier)
        self._contaminate(system.trust_tier)
        self._contaminate(discovery.trust_tier)

        self._scan_discovery_responses(discovery)
        self._validate_required_fields(skill, discovery)

        prompt_stack = self._build_prompt_stack(skill, system, discovery)
        output = _build_output(prompt_stack, self._context_trust_tier)
        _scan_output_or_raise(output, self._banish_list)

        canvas_id: str | None = None
        if self._canvas_store is not None and skill.mode in (SkillMode.IMAGE, SkillMode.TEMPLATE):
            canvas_record = await self._canvas_store.create_canvas(
                name=f"{skill.name} — {discovery.design_system_slug}",
                width=1920,
                height=1080,
            )
            canvas_id = canvas_record.id

        project_id = str(uuid.uuid4())
        project = DesignProject(
            id=project_id,
            name=f"{skill.name} ({system.name})",
            skill_slug=skill.slug,
            design_system_slug=system.slug,
            org_id=org_id,
            team_id=team_id,
            trust_tier=self._context_trust_tier,
            canvas_id=canvas_id,
            outputs=[output],
            discovery=discovery,
        )

        if self._project_store is not None:
            project = await self._project_store.create(project)

        return project
