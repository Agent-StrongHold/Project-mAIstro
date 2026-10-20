---
inventory-delta:
  packages/maistro-core/tests: +1
---

# #1207 — pin the format_markdown missing-field contract (empty substitution)

`transform.format_markdown` carried a dead `except KeyError` branch in
`_execute`: its `_render` helper returns `''` for any placeholder that does
not resolve, so the handler (and its "render placeholder so the user sees
what's absent" comment) documented behavior the renderer cannot produce.

The contract chosen is **documented empty substitution** — the behavior the
actually-used renderer already had — now stated on the module docstring, the
`FormatMarkdownIn.template` field description, the node `description`, and
the `_render` docstring; the unreachable `KeyError` path is removed. One
contract repair in `_render`: a placeholder with an empty dot-path (`{.}`)
previously fell through to `str(item)` (whole-item repr leak); it now renders
`''` like every other unresolvable placeholder.

**+1 `packages/maistro-core/tests/graph/nodes/test_sync_kinds.py`**:

- `test_format_markdown_malformed_and_none_placeholders_render_empty` — pins
  `{}` as literal braces (regex never matches), `{.}`/`{a.b.c}`-through-None/
  `{n}`-is-None as `''`, and `{a..b}` normalizing to the valid nested path
  `a.b`. Covers the new `if not parts: return ""` branch.

Rewritten in place (no count change):
`test_sync_kinds_branch_coverage.py::test_format_markdown_missing_field_renders_empty`
(renamed from `..._surfaces_placeholder`) now asserts the exact rendered rows
`- K1: \n- K2: ` and that the raw placeholder never leaks, instead of the
old docstring's claim that the dead KeyError path was exercised.
