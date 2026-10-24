---
id: SPEC-062326-7dcb
title: "ArtifactNode hierarchy and output-side Warden scanning for maistro-design"
repo: maistro-engine
kind: spec
status: Accepted
created: 2026-06-23
substrate:
  - maistro-engine#ADR-061
  - maistro-engine#ADR-100
  - maistro-engine#ADR-062
implements:
  - maistro-engine#ADR-062326-702b
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-design/tests/test_design.py
  - packages/maistro-design/tests/test_scan.py
layer: Ability
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-062326-7dcb: ArtifactNode hierarchy and output-side Warden scanning

## Context

ADR-062326-702b replaced `DesignOutput`'s flat `content: str` with a hierarchical
`ArtifactNode` tree (`file` / `blob` / `container`) so a single output can carry
multiple named, addressable artifacts — e.g. `rasters.characters.joe-smith`,
`svg.typography.header` — instead of one opaque string. It also added an
output-side Warden scan (mirroring the existing design-system-import scan) so
generated content is checked for injected scripts/prompt-injection/banished
patterns before it leaves `DesignEngine.generate()`, and renderer protocols
(`HTMLRenderer`, `SVGRenderer`, `TypographyRenderer`) that skills can require.
This SPEC documents the shipped implementation.

## Goals

- Document the actual `ArtifactNode`/`ArtifactKind`/`DesignOutput` shape as coded.
- Document `scan_design_output()` and how it tags findings with dotted artifact
  addresses.
- Document the renderer-availability gate (`_check_renderer_available`) and how
  it mirrors the existing `_check_image_gen` pattern.
- Map ADR-062326-702b's Gherkin acceptance scenarios to real tests.

## Non-goals

- Rendering pipeline orchestration (chaining rasterizers) — caller concern.
- Mutation of outputs post-generation — outputs are immutable once created.
- Streaming/chunked artifact generation.
- Typography rendering without an injected `TypographyRenderer` — optional, not
  a blocker.

## Decision

`packages/maistro-design/src/maistro_design/types.py`:

```python
class ArtifactKind(StrEnum):
    FILE = "file"
    BLOB = "blob"
    CONTAINER = "container"

@dataclass
class ArtifactNode:
    key: str
    kind: ArtifactKind
    format: OutputFormat | None = None
    value: str | bytes | None = None
    children: dict[str, ArtifactNode] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def get(self, address: str) -> ArtifactNode | None: ...   # dotted-path lookup
    def walk(self, _prefix: str = "") -> Iterator[tuple[str, ArtifactNode]]: ...  # FILE/BLOB leaves

@dataclass
class DesignOutput:
    root: ArtifactNode
    url: str | None = None
    trust_tier: TrustTier = TrustTier.T3
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def format(self) -> OutputFormat | None: ...   # root.format
    @property
    def content(self) -> str: ...    # root.value; raises DesignOutputShapeError unless
                                       # root.kind is FILE and root.value is str
```

`RendererKind = Literal["html", "svg", "typography"]`; `DesignSkill` gained
`required_renderer: RendererKind | None = None`. `OutputFormat` gained `JS`.

`packages/maistro-design/src/maistro_design/scan.py` (new module):

```python
def scan_design_output(
    output: DesignOutput, *,
    banish_list: InMemoryTrustBanishList | None = None,
    url_allowlist: tuple[str, ...] = DEFAULT_URL_ALLOWLIST,
) -> ScanReport: ...
```

Walks `output.root.walk()`, scanning each `FILE` leaf's string `value` through
the same `scan_blocking_patterns`/`find_external_urls` primitives used for
design-system-import scanning (`scan_design_system_content`, now also sourced
from this module rather than duplicated in `systems/importer.py`). `BLOB` leaves
are skipped (binary content is not pattern-scanned). Blocking flags are tagged
with the leaf's dotted address, e.g. `"svg.typography.header: matched script
pattern ..."`.

`packages/maistro-design/src/maistro_design/engine.py`:

```python
def _build_output(prompt_stack: str, trust_tier: TrustTier) -> DesignOutput: ...
    # wraps the assembled prompt stack as a single FILE-kind ArtifactNode

def _scan_output_or_raise(output: DesignOutput, banish_list: InMemoryTrustBanishList) -> None: ...
    # raises TrustBannedError if scan_design_output(...).passed is False

class DesignEngine:
    def __init__(
        self, skill_registry, system_registry,
        banish_list=None, trust_review_queue=None,
        canvas_store=None, image_gen=None,
        html_renderer: HTMLRenderer | None = None,
        svg_renderer: SVGRenderer | None = None,
        typography_renderer: TypographyRenderer | None = None,
    ) -> None: ...

    def _check_renderer_available(self, skill: Any) -> None: ...
        # raises SkillModeError if skill.required_renderer is set and the
        # matching renderer attribute (via _RENDERER_ATTRS) is None
```

`generate()`'s pipeline now runs `_check_image_gen` and
`_check_renderer_available` alongside `_check_compatibility` before
contamination, and scans the assembled prompt stack via `_scan_output_or_raise`
after `_build_prompt_stack` — independent of, and in addition to,
`_scan_discovery_responses` (which only sees `discovery.responses`, not a
skill's `system_prompt` or a design system's `design_md`/`tokens_css`).

`packages/maistro-design/src/maistro_design/protocols.py` gained
`HTMLRenderer`, `SVGRenderer`, `TypographyRenderer` (`@runtime_checkable`
`Protocol`), each with one `async` render method (`render`/`render_text`)
returning `bytes`.

`DesignEngine.generate()` itself only ever constructs a single `FILE`-kind
root (one prompt stack, format `MARKDOWN`) — it does not call an LLM or an
image-generation backend (ADR-061), so it has no real per-format content to
split into a multi-file tree and no `model_id`/pixel-dimension config to
drive `ImageGenClient`. `DesignOrchestrateNode` (`nodes.py`) is unaffected: it
reads `project.outputs[0].content`, which continues to resolve through the
`DesignOutput.content` property unchanged.

Two public, caller-facing functions in `engine.py` close the gap for callers
that *have* already produced real per-format content (post-LLM, post-image-gen):

```python
def build_multimodal_output(
    contents: dict[OutputFormat, str | bytes],
    *,
    trust_tier: TrustTier,
    banish_list: InMemoryTrustBanishList | None = None,
) -> DesignOutput: ...
    # One entry -> root.kind=FILE (str) or BLOB (bytes), matching generate()'s
    # single-artifact shape. Multiple entries -> root.kind=CONTAINER with one
    # FILE/BLOB child per format, keyed by OutputFormat.value ("html", "css",
    # "png", ...) since no real filenames exist pre-render. Always runs
    # scan_design_output() before returning; raises TrustBannedError on a
    # blocking finding. Reuses _scan_output_or_raise — no new scan logic.

async def persist_blobs(output: DesignOutput, canvas_store: CanvasStore) -> dict[str, str]: ...
    # Walks output.root.walk(), calls canvas_store.store_blob(node.value,
    # format=..., metadata=node.metadata) for every BLOB leaf, and returns
    # {dotted_address: stored_id}. Does not mutate output (outputs are
    # immutable once created — see Non-goals).
```

`packages/maistro-canvas/src/maistro_canvas/protocols.py`'s `CanvasStore`
protocol gained `store_blob(self, data: bytes, *, format: str, metadata:
dict[str, Any] | None = None) -> str` — purely additive (it's a `Protocol`;
no concrete class is forced to implement it unless something does
`isinstance(x, CanvasStore)`, which nothing in the codebase does).

## Acceptance criteria

- [x] Single-file HTML/text output nests under `root.kind == ArtifactKind.FILE`
- [x] `ArtifactNode.walk()` yields dotted addresses for every `FILE`/`BLOB` leaf,
      recursing through `CONTAINER` nodes
- [x] `ArtifactNode.get(address)` resolves a dotted path through `.children`
- [x] `DesignOutput.content`/`.format` raise `DesignOutputShapeError` for
      non-single-file (`container`/`blob`) roots
- [x] `OutputFormat.JS` exists
- [x] Warden scan detects `<script>` injection in generated output, tagged with
      the leaf's dotted address
- [x] `SkillModeError` raised if a skill's `required_renderer` has no matching
      renderer injected into `DesignEngine`
- [x] `generate()` succeeds when the required renderer is provided
- [x] `build_multimodal_output()` with a single `str`/`bytes` entry produces a
      `FILE`/`BLOB` root, matching `generate()`'s single-artifact shape
- [x] `build_multimodal_output()` with multiple entries produces a
      `CONTAINER` root with one `FILE`/`BLOB` child per format, keyed by
      `OutputFormat.value`
- [x] `build_multimodal_output()` raises `TrustBannedError` on blocking scan
      findings, same as `generate()`
- [x] `persist_blobs()` calls `canvas_store.store_blob()` once per `BLOB` leaf
      and returns one entry per leaf keyed by its dotted address

## Testing

`packages/maistro-design/tests/test_design.py`:
- `TestArtifactNode::test_get_resolves_dotted_address_through_containers`
- `TestArtifactNode::test_get_returns_none_for_unknown_address`
- `TestArtifactNode::test_walk_yields_dotted_addresses_for_every_leaf`
- `TestArtifactNode::test_walk_on_single_file_root_yields_its_own_key`
- `TestDesignOutput::test_content_and_format_for_single_file_output`
- `TestDesignOutput::test_content_raises_shape_error_for_container_root`
- `TestDesignOutput::test_content_raises_shape_error_for_blob_root`
- `TestDesignOutput::test_output_format_includes_js`
- `TestDesignEngineGenerate::test_generate_scans_assembled_output_for_script_injection`
- `TestDesignEngineGenerate::test_generate_output_is_a_file_artifact`
- `TestDesignEngineGenerate::test_generate_raises_skill_mode_error_for_missing_renderer`
- `TestDesignEngineGenerate::test_generate_succeeds_when_required_renderer_is_provided`
- `TestBuildMultimodalOutput::test_single_string_content_produces_file_root`
- `TestBuildMultimodalOutput::test_single_bytes_content_produces_blob_root`
- `TestBuildMultimodalOutput::test_multi_format_content_produces_container_root`
- `TestBuildMultimodalOutput::test_script_injection_raises_trust_banned_error`
- `TestBuildMultimodalOutput::test_persist_blobs_calls_store_blob_for_each_blob_leaf`

`packages/maistro-design/tests/test_scan.py` (`TestScanDesignOutput`):
- `test_clean_output_passes`
- `test_script_tag_is_blocking`
- `test_blocking_flag_is_tagged_with_dotted_address`
- `test_blob_leaves_are_not_pattern_scanned`
- `test_prompt_injection_phrase_is_blocking`
- `test_banish_list_match_is_blocking`
- `test_non_allowlisted_url_is_external_but_not_blocking`
- `test_multi_file_container_aggregates_findings_across_leaves`

## Open questions

- `DesignEngine.generate()` itself never builds a multi-file `container` root
  or a `blob` root, and that's intentional, not a gap: several builtin skills
  already set multi-format `output_formats` (`pitch-deck`, `product-demo-deck`,
  `landing-page`, `brand-guidelines`, `design-token-sheet` all declare 2
  formats), but `generate()` runs before any LLM/image-gen call, so it never
  has real per-format content to split — see `build_multimodal_output()`
  above for the caller-facing function that assembles real content into a
  multi-file/blob `DesignOutput` after that content exists. No skill currently
  sets `required_renderer` to a real value; wiring an actual rasterized skill
  through a renderer remains follow-up work, not blocked by anything in this
  SPEC.
- `packages/maistro-design/src` is not part of CI's `mypy --strict` package list
  (pre-existing gap, unrelated to this change); the 7 pre-existing strict errors
  in this package are unchanged by this work.

## References

- `packages/maistro-design/src/maistro_design/types.py`
- `packages/maistro-design/src/maistro_design/scan.py`
- `packages/maistro-design/src/maistro_design/engine.py`
- `packages/maistro-design/src/maistro_design/protocols.py`
- `packages/maistro-canvas/src/maistro_canvas/protocols.py`
- `packages/maistro-design/src/maistro_design/systems/importer.py`
- `packages/maistro-design/tests/test_design.py`
- `packages/maistro-design/tests/test_scan.py`
- `docs/adr/ADR-062326-702b-multi-modality-design-outputs-hierarchical-artifact-containers.md`
