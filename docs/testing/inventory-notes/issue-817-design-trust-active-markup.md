---
inventory-delta:
  packages/maistro-design/tests: +10
  packages/maistro-core/tests: +4
---
# Issue 817: Design trust active-markup corpus

The added Design tests exercise the shared pre-scan and output boundary with
prompt injection, script tags, handler attributes, dangerous SVG/image URLs,
data HTML, CSS network primitives, and active SVG elements. The Warden tests
pin the same reviewed active-markup vocabulary at the core detection boundary.
The render-output cases call `build_multimodal_output`, so they prove rejection
at the returned-artifact boundary rather than only inspecting a helper result.
