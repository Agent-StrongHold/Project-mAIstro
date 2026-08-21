---
id: ADR-062326-702b
title: Multi-modality design outputs and hierarchical artifact containers
repo: maistro-engine
kind: adr
status: Implemented
created: 2026-06-23
accepted: 2026-06-23
implemented: 2026-06-23
substrate:
  - maistro-engine#ADR-061
  - maistro-engine#ADR-100
  - maistro-engine#ADR-062
implements: []
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
source:
  - packages/maistro-design/src/maistro_design/types.py
  - packages/maistro-design/src/maistro_design/scan.py
  - packages/maistro-design/src/maistro_design/engine.py
  - packages/maistro-design/src/maistro_design/protocols.py
  - packages/maistro-canvas/src/maistro_canvas/protocols.py
ac-modules:
  AC-1: maistro_design.engine
  AC-2: maistro_design.engine
  AC-3: maistro_design.engine
  AC-4: maistro_design.scan
  AC-5: maistro_design.engine
  AC-6: maistro_design.engine
  AC-7: maistro_design.engine
layer: Ability
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-06-23
  - status: Accepted
    date: 2026-06-23
  - status: Implemented
    date: 2026-06-23
---

# ADR-062326-702b: Multi-modality design outputs and hierarchical artifact containers

## Context

ADR-061 specifies that `DesignEngine` builds a prompt stack but does not emit the actual artifact
(that is the caller's responsibility after LLM invocation). Today `DesignOutput.content` is a single
`str` field, which works for text formats (HTML, CSS, Markdown, JSON) but fails for:

1. **Multi-file outputs** — HTML+CSS+JS require separate files, not a single string.
2. **Binary formats** — PNG, PDF, SVG as bytes (not base64'd strings).
3. **Nested/scoped artifacts** — a single output should be able to hold multiple assets
   (e.g., `rasters.characters.{name}`, `svg.typography.{section}`, `html.pages.{slug}`),
   not a flat collection.

Current workarounds (storing URLs in the `url` field, relying on CanvasRecord for rasters)
do not compose with the trust-tier model (ADR-061 §3) or survive session/project lifecycle
boundaries.

## Decision

### 1. Hierarchical artifact container replaces single-string `DesignOutput.content`

```python
@dataclass
class ArtifactNode:
    """A single artifact (file, binary blob, or nested container)."""
    key: str  # kebab-case identifier within parent, e.g. "main", "sidebar", "characters"
    kind: Literal["file", "blob", "container"]  # file/text, binary data, or nested
    format: OutputFormat  # HTML, CSS, PNG, SVG, etc.
    value: str | bytes | None = None  # content for file/blob; None for container
    children: dict[str, ArtifactNode] = field(default_factory=dict)  # nested artifacts
    metadata: dict[str, Any] = field(default_factory=dict)  # e.g. "width": 1920

@dataclass
class DesignOutput:
    """A generated design artifact (multi-modality, hierarchical)."""
    root: ArtifactNode  # root container holding the artifact tree
    trust_tier: TrustTier = TrustTier.T3
    metadata: dict[str, Any] = field(default_factory=dict)  # output-level metadata
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
```

Examples:

- **Single-file HTML output** → `root.kind="file"`, `root.format=HTML`, `root.value="<html>..."`
- **Landing page (HTML+CSS+JS)** → `root.kind="container"`, `root.children={"index.html": File(HTML), "style.css": File(CSS), "app.js": File(JS)}`
- **Hero image** → `root.kind="blob"`, `root.format=PNG`, `root.value=<bytes>`
- **SVG with nested typography** → `root.kind="container"`, `root.format=SVG`, `root.children={"header": Container(typography.subfields...), "body": ...}`
- **Pitch deck with asset pack** → `root.kind="container"`, `root.children={"slides.html": File(HTML), "assets.rasters": Container({"slide-1-hero.png": Blob, ...}), "fonts": Container({...})}`

### 2. Output scanning (Warden) gates multi-modality artifacts

All output content (HTML, SVG, JS, CSS strings) is scanned before return, since outputs carry
the session's contaminated trust tier. Scanning detects script injection, eval, iframes,
prompt-injection phrasing, external URL fetches (against an allowlist), and steganographic content.
Raises `TrustBannedError` if banished patterns are found. This mirrors the design-system-import
scan (ADR-100 § 2) applied at output time rather than input time.

### 3. Binary-safe asset store (canvas or new)

Blob artifacts must be persisted. Canvas asset store (ADR-040) is the natural home for
`DesignOutput` blobs; the DesignEngine integrates with `CanvasStore` protocol but does not
require it (callers can substitute an in-memory store or cloud blob store).

### 4. Add `JS` to `OutputFormat`

```python
class OutputFormat(StrEnum):
    HTML = "html"
    MARKDOWN = "markdown"
    PPTX = "pptx"
    PNG = "png"
    SVG = "svg"
    PDF = "pdf"
    CSS = "css"
    JSON = "json"
    JS = "js"      # ← NEW
```

### 5. Renderer protocols per modality

Define abstract interfaces for each renderer backend (caller injects):

```python
@runtime_checkable
class HTMLRenderer(Protocol):
    async def render(self, html: str, css: str | None = None) -> bytes: ...  # → PNG/PDF

@runtime_checkable
class SVGRenderer(Protocol):
    async def render(self, svg: str, format: Literal["png", "pdf"]) -> bytes: ...

@runtime_checkable
class TypographyRenderer(Protocol):
    async def render_text(self, text: str, font: TypographyToken, size: str) -> bytes: ...
```

The engine accepts these optionally; skills declare which renderers they require. If a skill
needs an unavailable renderer, raise `SkillModeError` (mirroring the image_gen check today).

### 6. DesignOrchestrateNode integrates hierarchical outputs

The DAG node now produces `DesignOutput` with hierarchical containers, not flat strings.
Downstream nodes (or the DAG executor) can traverse the tree and fan out to per-artifact
processing (store, serve, convert formats, etc.).

## Acceptance criteria

```gherkin
@AC-1
Scenario: Single-file output is a file artifact
  Given a skill with mode=PROTOTYPE, output_formats=[HTML]
  When generate() is called
  Then output.root.kind == "file"
  And output.root.format == MARKDOWN
  # generate() always wraps the assembled prompt stack as Markdown
  # (_build_output() hardcodes format=OutputFormat.MARKDOWN) — it never
  # branches on a skill's declared output_formats, since it has not called
  # an LLM and so has no real HTML/CSS/JS content to format as. A skill's
  # output_formats only constrains what a caller may later assemble via
  # build_multimodal_output() once it has real per-format content.

@AC-2
Scenario: Multi-file landing page (HTML+CSS+JS)
  Given a caller has already produced separate HTML/CSS/JS content (e.g. from per-format LLM calls downstream of generate())
  When build_multimodal_output({HTML: html_text, CSS: css_text, JS: js_text}, trust_tier=tier) is called
  Then output.root.kind == "container"
  And output.root.children contains "html", "css", "js", each kind="file"

@AC-3
Scenario: PNG output is a blob
  Given a caller has already produced PNG bytes (e.g. from an ImageGenClient call downstream of generate())
  When build_multimodal_output({PNG: png_bytes}, trust_tier=tier) is called
  Then output.root.kind == "blob", format=PNG, value is bytes

@AC-4
Scenario: SVG with nested typography hierarchy (caller-assembled)
  Given a caller hand-builds an ArtifactNode tree with a nested "typography" container (e.g. from per-section TypographyRenderer output)
  When the caller scans it via scan_design_output() before persisting
  Then nested containers are supported structurally
  And findings are tagged with their full dotted address (e.g. "typography.header: ...")
  # build_multimodal_output()'s flat dict signature builds one level of
  # nesting (format -> leaf); deeper hand-built hierarchies remain a caller
  # concern, consistent with "Out of scope" below.

@AC-5
Scenario: Warden scan detects <script> injection in HTML output
  Given output containing "<script>alert(1)</script>"
  When output is scanned before return
  Then TrustBannedError is raised

@AC-6
Scenario: SkillModeError if HTML renderer unavailable
  Given a skill requiring HTMLRenderer (mode=TEMPLATE)
  When DesignEngine is constructed without an HTMLRenderer
  Then generate() raises SkillModeError

@AC-7
Scenario: Blob artifact is persisted via CanvasStore
  Given a DesignOutput containing one or more BLOB-kind leaves
  When persist_blobs(output, canvas_store) is called
  Then canvas_store.store_blob() is awaited once per BLOB leaf
  And the returned mapping has one entry per leaf, keyed by its dotted address
```

## Corrections (2026-06-28)

A completeness audit found this ADR self-contradictory: the Examples list under Decision §1
described single-file output as `root.kind="file"` directly, while the original Acceptance
criteria's first Gherkin scenario asserted the opposite — `root.kind="container"` with the file
nested under `children["index"]`. The shipped implementation matches the Examples (`root.kind="file"`);
`DesignOutput.content`/`.format` and `DesignOrchestrateNode`'s `project.outputs[0].content` both
depend on that shape. The Acceptance criteria above has been corrected to match.

The audit also found that Decision §6 ("DesignOrchestrateNode integrates hierarchical outputs")
overstated what was implemented: `generate()` is, and remains, a pre-LLM prompt-stack builder
(per ADR-061 and `engine.py`'s own module docstring — it does not call an LLM or an image-generation
backend, so it has no real per-format content to split into a multi-file tree and no `model_id`/
pixel-dimension config to drive `ImageGenClient`). The original Gherkin scenarios for multi-file,
blob, and nested-typography outputs described behavior `generate()` never produced. Rather than
force those behaviors into `generate()` (which would mean fabricating content or inventing
unspecified config), this revision adds caller-facing assembly functions —
`build_multimodal_output()` and `persist_blobs()` in `engine.py` — that a caller invokes after it
has already produced real per-format content via its own LLM/image-gen step. The Acceptance
criteria scenarios above now describe these functions rather than `generate()`. `generate()` and
`DesignOrchestrateNode` are unchanged.

## Consequences

**Positive:**
- Multi-file outputs (HTML+CSS+JS) compose naturally without flattening or post-processing.
- Binary-safe; PNG/PDF/SVG bytes do not require base64 encoding.
- Hierarchical nesting mirrors skill intent (e.g., "hero section" → `root.children.hero`).
- Warden scanning per output (not per skill) catches runtime injection from LLM outputs.
- Trust tier is carried through the tree; all artifacts are downgraded together.

**Negative:**
- More complex than a single-string output; callers traverse the tree instead of reading `.content`.
- HTML renderer (→ PNG/PDF rasterization) requires a headless browser or wkhtmltopdf-class backend.
- Rendering backends are optional; skills without their renderer raise errors (non-composable until a caller provides one).

**Neutral:**
- Backward compatibility: existing text-only skills produce `root.kind="file"` (can be read as `.root.value`).

## Out of scope

- Rendering pipeline orchestration (how to chain rasterizers); that is a caller concern.
- Mutation of outputs post-generation (editing individual artifacts). Outputs are immutable once created.
- Streaming or chunked artifact generation (ADR-062 graph streaming may interact).
- Typography rendering without an injected renderer (not a blocker, just an optional feature).
