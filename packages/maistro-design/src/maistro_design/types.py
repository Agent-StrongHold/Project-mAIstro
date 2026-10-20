"""maistro-design types: skills, design systems, projects, outputs, and domain errors."""

from __future__ import annotations

import base64
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from maistro.types.errors import AgentError
from maistro_design.trust import TrustTier

RendererKind = Literal["html", "svg", "typography"]


class SkillMode(StrEnum):
    PROTOTYPE = "prototype"
    DECK = "deck"
    TEMPLATE = "template"
    DESIGN_SYSTEM = "design-system"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"


class OutputFormat(StrEnum):
    HTML = "html"
    MARKDOWN = "markdown"
    PPTX = "pptx"
    PNG = "png"
    SVG = "svg"
    PDF = "pdf"
    CSS = "css"
    JSON = "json"
    JS = "js"
    DOCX = "docx"
    REACT_TSX = "react_tsx"


class RenderSlot(StrEnum):
    """A renderer capability slot (SPEC-070426-a22b / ADR-070426-f2a0).

    A slot is a capability the system *can* have. A provider fills one or more slots;
    a skill declares the slot it needs via ``DesignSkill.render_slot``. ``FIXED_PAGE`` is
    the canvas-native floor — always present, never supplied by an external plugin.
    """

    FIXED_PAGE = "renderer.fixed-page"  # slides/flyers/posters/cards/covers — canvas-native
    DECK = "renderer.deck"  # multi-page decks -> PPTX/PDF
    REFLOWABLE_WEB = "renderer.reflowable-web"  # responsive HTML/CSS — canvas cannot reflow
    VIDEO = "renderer.video"  # HTML -> MP4
    DESIGN_SYSTEMS_LIVE = "designsystems.live"  # live corpus vs. vendored snapshot


class ArtifactKind(StrEnum):
    """Shape of a single ArtifactNode — leaf text, leaf binary, or a nested container."""

    FILE = "file"  # text content (HTML, CSS, JS, SVG markup, Markdown, ...)
    BLOB = "blob"  # binary content (PNG, PDF, ...)
    CONTAINER = "container"  # holds named children, no content of its own


@dataclass
class ArtifactNode:
    """One node in a hierarchical design-output tree (ADR-062326-702b).

    A `FILE`/`BLOB` node carries `value`; a `CONTAINER` node carries `children` keyed
    by kebab-case slug, e.g. root.children["characters"].children["joe-smith"] for an
    address of "characters.joe-smith". `format` is the leaf's `OutputFormat`; containers
    may leave it `None` (the modality is implied by their children).
    """

    key: str
    kind: ArtifactKind
    format: OutputFormat | None = None
    value: str | bytes | None = None
    children: dict[str, ArtifactNode] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def get(self, address: str) -> ArtifactNode | None:
        """Resolve a dotted address (e.g. "characters.joe-smith") against this node's children."""
        node = self
        for part in address.split("."):
            child = node.children.get(part)
            if child is None:
                return None
            node = child
        return node

    def walk(self, _prefix: str = "") -> Iterator[tuple[str, ArtifactNode]]:
        """Yield (dotted_address, node) for every FILE/BLOB leaf beneath this node."""
        address = f"{_prefix}.{self.key}" if _prefix else self.key
        if self.kind is ArtifactKind.CONTAINER:
            for child in self.children.values():
                yield from child.walk(_prefix=address)
        else:
            yield address, self


@dataclass(frozen=True)
class DiscoveryField:
    """One question in a skill's discovery form. Must be answered before generation."""

    key: str
    label: str
    description: str
    field_type: str = "text"  # text | select | multiselect | color | number
    options: tuple[str, ...] = ()
    required: bool = True
    default: str | None = None
    trust_tier: TrustTier = TrustTier.T3  # user-supplied fields default to untrusted

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "description": self.description,
            "field_type": self.field_type,
            "options": list(self.options),
            "required": self.required,
            "default": self.default,
        }


@dataclass
class DesignSkill:
    """Composable design skill — the atomic unit of design capability.

    Mirrors open-design's SKILL.md concept, backed by maistro-core's trust-tier model.
    """

    slug: str  # kebab-case, e.g. "login-flow"
    name: str
    mode: SkillMode
    description: str
    discovery_form: list[DiscoveryField] = field(default_factory=list)
    system_prompt: str = ""
    compatible_design_systems: list[str] = field(default_factory=list)  # [] = all
    featured: bool = False
    trust_tier: TrustTier = TrustTier.T0
    output_formats: list[OutputFormat] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    required_renderer: RendererKind | None = None
    # Capability slot this skill needs (SPEC-070426-a22b). None => no external renderer
    # required (canvas-native fixed-page) => always available regardless of installed plugins.
    render_slot: RenderSlot | None = None


@dataclass(frozen=True)
class ColorToken:
    name: str
    value: str
    group: str = "brand"


@dataclass(frozen=True)
class TypographyToken:
    name: str
    family: str
    size: str
    weight: str = "400"
    line_height: str | None = None
    letter_spacing: str | None = None


@dataclass(frozen=True)
class SpacingToken:
    name: str
    value: str


@dataclass
class DesignSystem:
    """Brand/style specification — colors, typography, tokens, and design guidelines.

    Mirrors open-design's design-systems/{slug}/ folder (manifest.json + DESIGN.md + tokens.css).
    Built-in systems are TrustTier.T0; user-loaded systems default to TrustTier.T2.
    """

    slug: str
    name: str
    description: str
    colors: list[ColorToken] = field(default_factory=list)
    typography: list[TypographyToken] = field(default_factory=list)
    spacing: list[SpacingToken] = field(default_factory=list)
    tokens_css: str = ""
    design_md: str = ""
    components: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    trust_tier: TrustTier = TrustTier.T0

    def get_color(self, name: str) -> ColorToken | None:
        return next((c for c in self.colors if c.name == name), None)

    def get_typography(self, name: str) -> TypographyToken | None:
        return next((t for t in self.typography if t.name == name), None)


@dataclass
class DiscoveryResult:
    """Collected responses from a skill's discovery form."""

    skill_slug: str
    responses: dict[str, str]
    design_system_slug: str = "default"
    trust_tier: TrustTier = TrustTier.T3  # user-supplied, always starts untrusted
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass
class DesignOutput:
    """A generated design artifact — a hierarchical tree of named ArtifactNodes.

    Single-file text outputs (the only shape the engine emits today) have
    root.kind == FILE; multi-file and binary outputs nest under a CONTAINER root.
    `.content`/`.format` are convenience accessors for the single-file case.
    """

    root: ArtifactNode
    url: str | None = None
    trust_tier: TrustTier = TrustTier.T3
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    # Producer provenance (#709). An artifact shipped to a user with no record
    # of what made it; `metadata` is a free-form dict and could hold anything,
    # which is exactly why it is not where an identity belongs. Filled from the
    # ambient execution context at write time when the caller does not name it.
    run_id: str = ""
    node_run_id: str = ""
    attempt_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize the supported single-file API representation.

        Binary and container outputs do not have inline text content. They are
        represented by their kind and URL/metadata instead of calling
        ``content`` and turning a valid persisted read into a server error.
        """
        content = (
            self.content
            if self.root.kind is ArtifactKind.FILE and isinstance(self.root.value, str)
            else None
        )
        return {
            "format": self.format.value if self.format is not None else None,
            "content": content,
            "url": self.url,
            "trust_tier": self.trust_tier.value,
            "metadata": self.metadata,
            "artifact_kind": self.root.kind.value,
            "run_id": self.run_id,
            "node_run_id": self.node_run_id,
            "attempt_id": self.attempt_id,
        }

    @property
    def format(self) -> OutputFormat | None:
        return self.root.format

    @property
    def content(self) -> str:
        """Text content of a single-file output. Raises for hierarchical/binary outputs."""
        if self.root.kind is not ArtifactKind.FILE or not isinstance(self.root.value, str):
            msg = (
                "DesignOutput.content is only valid for single-file text outputs "
                "(root.kind == ArtifactKind.FILE); use .root to traverse hierarchical "
                "or binary outputs"
            )
            raise DesignOutputShapeError(msg)
        return self.root.value


# ─── DesignProject payload (stable Attempt-result DTO) ────────────────────────

#: Tag wrapping a BLOB leaf's bytes: durable Attempt evidence is JSON, so binary
#: values ride base64 and are restored by `DesignProject.from_payload`.
_BYTES_TAG = "__bytes_b64__"


def _payload_value(value: str | bytes | None) -> str | dict[str, str] | None:
    if isinstance(value, bytes):
        return {_BYTES_TAG: base64.b64encode(value).decode("ascii")}
    return value


def _payload_from_value(value: Any) -> str | bytes | None:
    if isinstance(value, dict) and set(value) == {_BYTES_TAG}:
        encoded = value[_BYTES_TAG]
        return base64.b64decode(str(encoded))
    if isinstance(value, str | bytes) or value is None:
        return value
    raise TypeError("ArtifactNode leaf values must be str, bytes, or None")


def _artifact_payload(node: ArtifactNode) -> dict[str, Any]:
    return {
        "key": node.key,
        "kind": node.kind.value,
        "format": node.format.value if node.format is not None else None,
        "value": _payload_value(node.value),
        "children": {key: _artifact_payload(child) for key, child in node.children.items()},
        "metadata": node.metadata,
    }


def _artifact_from_payload(data: dict[str, Any]) -> ArtifactNode:
    return ArtifactNode(
        key=data["key"],
        kind=ArtifactKind(data["kind"]),
        format=OutputFormat(data["format"]) if data["format"] is not None else None,
        value=_payload_from_value(data["value"]),
        children={key: _artifact_from_payload(child) for key, child in data["children"].items()},
        metadata=data["metadata"],
    )


def _output_payload(output: DesignOutput) -> dict[str, Any]:
    return {
        "root": _artifact_payload(output.root),
        "url": output.url,
        "trust_tier": output.trust_tier.value,
        "metadata": output.metadata,
        "created_at": output.created_at.isoformat(),
        "run_id": output.run_id,
        "node_run_id": output.node_run_id,
        "attempt_id": output.attempt_id,
    }


def _output_from_payload(data: dict[str, Any]) -> DesignOutput:
    return DesignOutput(
        root=_artifact_from_payload(data["root"]),
        url=data["url"],
        trust_tier=TrustTier(data["trust_tier"]),
        metadata=data["metadata"],
        created_at=datetime.fromisoformat(data["created_at"]),
        run_id=data["run_id"],
        node_run_id=data["node_run_id"],
        attempt_id=data["attempt_id"],
    )


def _discovery_payload(discovery: DiscoveryResult) -> dict[str, Any]:
    return {
        "skill_slug": discovery.skill_slug,
        "responses": discovery.responses,
        "design_system_slug": discovery.design_system_slug,
        "trust_tier": discovery.trust_tier.value,
        "created_at": discovery.created_at.isoformat(),
    }


def _discovery_from_payload(data: dict[str, Any]) -> DiscoveryResult:
    return DiscoveryResult(
        skill_slug=data["skill_slug"],
        responses=data["responses"],
        design_system_slug=data["design_system_slug"],
        trust_tier=TrustTier(data["trust_tier"]),
        created_at=datetime.fromisoformat(data["created_at"]),
    )


@dataclass
class DesignProject:
    """Top-level design project combining skill + design system + outputs."""

    id: str
    name: str
    skill_slug: str
    design_system_slug: str
    org_id: str
    trust_tier: TrustTier = TrustTier.T3
    team_id: str | None = None
    canvas_id: str | None = None
    outputs: list[DesignOutput] = field(default_factory=list)
    discovery: DiscoveryResult | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "skill_slug": self.skill_slug,
            "design_system_slug": self.design_system_slug,
            "org_id": self.org_id,
            "team_id": self.team_id,
            "trust_tier": self.trust_tier,
            "canvas_id": self.canvas_id,
            "output_count": len(self.outputs),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    def to_payload(self) -> dict[str, Any]:
        """JSON-stable DTO of the full project — not the lossy `to_dict` summary.

        Durable RunStores JSON-hydrate `Attempt.result`, so the canonical Design
        adapter persists this payload as the Attempt's evidence and rebuilds the
        domain object from it on replay (`from_payload`). BLOB leaves ride the
        `_BYTES_TAG` base64 envelope; enums, timestamps, and nested
        outputs/discovery are restored to their declared types.
        """
        return {
            "id": self.id,
            "name": self.name,
            "skill_slug": self.skill_slug,
            "design_system_slug": self.design_system_slug,
            "org_id": self.org_id,
            "team_id": self.team_id,
            "trust_tier": self.trust_tier.value,
            "canvas_id": self.canvas_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "outputs": [_output_payload(output) for output in self.outputs],
            "discovery": (
                _discovery_payload(self.discovery) if self.discovery is not None else None
            ),
        }

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> DesignProject:
        """Rebuild a `DesignProject` from `to_payload` output."""
        return cls(
            id=data["id"],
            name=data["name"],
            skill_slug=data["skill_slug"],
            design_system_slug=data["design_system_slug"],
            org_id=data["org_id"],
            team_id=data["team_id"],
            trust_tier=TrustTier(data["trust_tier"]),
            canvas_id=data["canvas_id"],
            outputs=[_output_from_payload(output) for output in data["outputs"]],
            discovery=(
                _discovery_from_payload(data["discovery"])
                if data["discovery"] is not None
                else None
            ),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
        )


# ─── Domain errors ────────────────────────────────────────────────────────────


class DesignError(AgentError):
    code = "DESIGN_ERROR"


class SkillNotFoundError(DesignError):
    code = "SKILL_NOT_FOUND"


class DesignSystemNotFoundError(DesignError):
    code = "DESIGN_SYSTEM_NOT_FOUND"


class CatalogImportPolicyError(DesignError, ValueError):
    """Raised when a catalog slug or its resolved files violate the boundary."""

    code = "CATALOG_IMPORT_POLICY"


class DiscoveryIncompleteError(DesignError):
    code = "DISCOVERY_INCOMPLETE"


class SkillModeError(DesignError):
    code = "SKILL_MODE_ERROR"


class DesignOutputShapeError(DesignError):
    """Raised when a single-file accessor (.content/.format) is used on a multi-artifact output."""

    code = "DESIGN_OUTPUT_SHAPE_ERROR"


class DesignProjectNotFoundError(DesignError):
    code = "DESIGN_PROJECT_NOT_FOUND"


class DesignScopeError(DesignError):
    """Raised when a project names no scope, or names one the caller is not in.

    `org` is a soft scope axis (ADR-068), so nothing in the database resolves it
    to an owner -- which is exactly why the store has to. Migration 003's
    foreign key looked like this guard and was not: it asked whether the org was
    a row in a table nothing writes, and so refused every value (#326).
    """

    code = "DESIGN_SCOPE_ERROR"


class IncompatibleDesignSystemError(DesignError):
    code = "INCOMPATIBLE_DESIGN_SYSTEM"


class TrustBannedError(DesignError):
    """Raised when a banish-list pattern is found in a discovery response."""

    code = "TRUST_BANNED"


class TrustUpgradeRequiredError(DesignError):
    """Raised when content requires admin approval before trust can be upgraded."""

    code = "TRUST_UPGRADE_REQUIRED"
