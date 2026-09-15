---
inventory-delta:
  packages/maistro-core/tests: +9
  packages/maistro-design/tests: +28
  packages/hive-conductor/backend/tests: +1
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
string prefixes. The repair adds link stylesheet and video poster fetch surfaces to
the shared Warden vocabulary and verifies both pre-scan recommendations and final
render rejection for each. The repair regression also covers Warden's system-prompt
query rule at both the pre-scan and returned-artifact boundaries. The shared visual
classification remains fail-closed even for a URL that the prose/import allowlist
would otherwise permit, matching the browser renderer's CSS boundary. Server-side
PDF/PPTX/DOCX/PNG renderer entry points now call the same `scan_design_text` boundary
before backend dispatch, so selecting a renderer cannot bypass returned-artifact
enforcement.
