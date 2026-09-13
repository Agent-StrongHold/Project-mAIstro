---
inventory-delta:
  packages/maistro-core/tests: +6
  packages/maistro-design/tests: +19
---
# Issue 817: Design trust active-markup corpus

The added Design tests exercise the shared pre-scan and output boundary with
prompt injection, script tags, handler attributes, dangerous SVG/image URLs,
data HTML, CSS network primitives, CSS escapes, HTML entities, and active SVG
elements. The Warden tests pin the same reviewed active-markup vocabulary at the
core detection boundary, including the shared entity/CSS escape normalization.
The render-output cases call `build_multimodal_output`, so they prove rejection
at the returned-artifact boundary rather than only inspecting a helper result. The
hostile corpus also covers a lookalike subdomain of an allowlisted font origin,
which verifies that CSS network checks compare parsed URL authorities rather than
string prefixes.
