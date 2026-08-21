---
id: SPEC-070426-457b
title: "Canvas structured exporters — layer tree to editable PPTX and absolute-positioned HTML"
repo: maistro-engine
kind: spec
status: Implemented
created: 2026-07-04
substrate:
  - maistro-engine#ADR-062326-702b
implements:
  - maistro-engine#ADR-070426-f2a0
related:
  - maistro-engine#ADR-062326-616c
  - maistro-engine#SPEC-070426-a22b
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
  - behavioral
tests:
  - packages/maistro-canvas/tests/test_export.py
layer: Ability
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-070426-457b: Canvas structured exporters (PPTX / HTML)

## Context

`maistro-canvas` is a fixed-layout page compositor: ordered layers with
`x, y, scale, rotation, z_index`, where layers are background / generated-image /
graphic / text-with-typography. Today it flattens to raster (PIL/RGBA) and the book
pipeline emits PDF. Because the layer tree is **structured** (each layer's kind,
position, and text style are known), it maps 1:1 to structured export targets — a text
layer becomes an editable PPTX text box or an HTML text node, not a screenshot. This
SPEC adds those exporters, which fill `renderer.fixed-page` (and `renderer.deck` for
multi-page) natively — the plugin-free floor of ADR-070426-f2a0. It is a sibling to
ADR-062326-616c (which added React/TSX code export); this adds PPTX and HTML from the
canvas layer tree, and has **no external dependency**.

## Goals

- `export_pptx(canvases) -> bytes` — each canvas → one slide; each layer → a native shape
  (text layer → editable text box; image/graphic → picture) at matched geometry. `python-pptx`.
- `export_html(canvas) -> str` — each layer → an absolutely-positioned element; single-file, inlined assets.
- A `document = ordered list of canvases` wrapper for multi-page decks (the book pipeline already does this for PDF).
- Register these as the canvas-native providers for `renderer.fixed-page` / `renderer.deck` (per SPEC-070426-a22b).

## Non-goals

- Reflowable / responsive web or long-document reflow — that is `renderer.reflowable-web` (Open Design, SPEC-070426-6ea8).
- Video (`renderer.video`).
- The auto-layout "what goes where" intelligence — that is the skill + design-system prompt stack, not the exporter.
- Re-implementing the existing PDF/PNG flatten (already shipped); this reuses it.

## Decision

### Layer → target mapping
| Canvas layer | PPTX | HTML |
|---|---|---|
| background | slide background / full-bleed picture | root element background |
| image / graphic | picture shape at `x,y,w,h` | `<img>` absolutely positioned |
| text (+ `text_style`) | **editable text box**; font/size/color/weight/alignment mapped | `<div>` with matching CSS |

Geometry: canvas px → EMU for PPTX; canvas px → `position:absolute` px (or %) for HTML.
Text stays text end-to-end — this is what makes PPTX output editable and is already
enforced by da Vinci's "render text as a canvas text layer, never bake into the image" rule.

### Multi-page
`Document(canvases: list[CanvasRecord])` → N-slide PPTX / multi-section HTML / (existing) multi-page PDF.

### Availability
These exporters are always-present providers: `renderer.fixed-page` is filled
unconditionally, so fixed-layout skills (flyer, poster, card, cover, single-canvas slide)
render for every user regardless of installed plugins.

## Acceptance criteria

- A canvas with a background + image + two text layers exports to a PPTX whose text boxes are editable in PowerPoint and positioned to match.
- The same canvas exports to single-file HTML that renders visually equivalent to the raster flatten.
- A 3-canvas `Document` exports to a 3-slide PPTX.
- With zero plugins installed, fixed-page/deck skills are offered and render (proves the plugin-free floor).

## Testing

- Unit: layer→shape geometry math (px↔EMU, px↔CSS); text-style fidelity round-trip.
- Golden: export a known canvas → PPTX/HTML, diff against fixtures.
- Integration: `renderer.fixed-page` availability with no external providers registered.

## Open questions

- DOCX: out of scope now (reflowable). Support later as a positioned-frame export, or never?
- Font embedding in PPTX vs. relying on system fonts / design-system web fonts.
- How faithfully must HTML match raster when a layer uses an effect PIL applies but CSS cannot?

## References

- ADR-070426-f2a0 — deciding ADR. SPEC-070426-a22b — substrate (slot registration).
- ADR-062326-616c — sibling code-export capability (React/TSX).
- ADR-062326-702b — hierarchical artifact containers (export output shape).
