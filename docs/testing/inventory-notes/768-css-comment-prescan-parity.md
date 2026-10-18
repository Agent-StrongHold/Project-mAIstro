---
inventory-delta:
  packages/maistro-design/tests: +3
---

# 768-css-comment-prescan-parity

Repair round for the prior verification finding: *"executed probe returned
tier=t3 recommendation=upgrade for renderer-blocked CSS"* —
`scan.py`'s `_check_style` split `style` attributes into declarations and
checked each against the property/value allowlists, but the browser boundary
(`visualArtifactRenderer.tsx` `sanitizeStyle`) rejects the whole attribute
earlier, in its `OBFUSCATED_CSS` gate, when it contains a CSS comment (`/*`)
or a backslash escape. The verifier's probe
`<div style="color: red/*...*/">` therefore classified as clean CSS on the
pre-scan side while the renderer stripped it — exactly the #817 divergence
this issue exists to prevent: content the boundary blocks was recommended for
trust upgrade.

## Repair

`_check_style` now mirrors the renderer's gate first: an `_OBFUSCATED_CSS`
match (`\` or `/*` anywhere in the attribute) adds `css-network-or-code` and
stops, before any declaration parsing. Escapes/comments are how a blocked
construct hides from a lexical checker (`ur\6c(` vs `url(`), which is why the
renderer rejects them wholesale rather than trying to decode every browser
CSS grammar; the pre-scan cannot be more permissive than the boundary it
vouches for.

## Evidence

- The exact failing probe re-executed after the fix:
  `scan_and_record('<div style="color: red/*...*/">…')` →
  `tier=skull`, `recommendation=banish`,
  `flags=('css-network-or-code',)` — no longer upgradeable.
- New pinned cases (the +3 above):
  - `test_scan.py::test_hostile_constructs_carry_the_renderer_reason` —
    `color: red/* inline */` and `color: \72 ed` both map to
    `css-network-or-code`;
  - `test_trust_prescan.py::test_renderer_blocked_markup_is_never_upgraded` —
    the CSS-comment probe asserts SKULL + `banish`, never `upgrade`.
- `uv run pytest packages/maistro-design/tests/test_scan.py
  packages/maistro-design/tests/test_trust_prescan.py -q` — 58 passed
  (55 before this round), safe presentation templates unchanged.
