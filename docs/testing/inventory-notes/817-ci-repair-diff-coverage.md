---
inventory-delta:
  packages/maistro-core/tests: +5
  packages/maistro-design/tests: +7
---

# 817 CI repair: diff-coverage floors and the dead @import arm

Repair round for #817 against the CI failures recorded at `f517200`:
the Coverage gate failed diff coverage on three files
(`scan.py` 85.9%, `normalize.py` 85.7%, `design_render.py` 81.8% of changed
lines; floor 90%), and the Quality gate failed the acceptance-state ratchet
because the `design_coverage@33.9095` grant was superseded by three
independently landed notes (`auto-1138`, `auto-1158`, `auto-48`).

## Why the tests were added (and what they found)

Writing the `@import` coverage for `_css_network_or_code_is_blocking`
exposed a real detection gap, not just an uncovered line: the Warden
leetspeak fold maps `@` to `a` inside mixed tokens, which rewrote
`@import "https://evil.example/x.css"` into `aimport "..."` in the detection
view. The `@import` arm of the CSS network/code vocabulary — both the active
and the visual-artifact copy — matches the at-rule verbatim and therefore
could never fire, while the reviewed TS sink
(`visualArtifactRenderer.tsx` `NETWORK_OR_CODE_CSS`) blocked the same value.
A payload with no `url(` token and no markup tag passed every Python
scanner. `fold_bounded_leetspeak` now leaves a leading `@` alone (an
at-rule, not leetspeak); mid-token `@` (`m@il`) still folds.

## Test deltas

- `packages/maistro-core/tests` (+5): the CSS-escape-decoding corpus in
  `warden/test_detector.py` gained the at-rule spelling pin (`@import ...`
  survives the fold unchanged), a non-hex escape (`back\slash`), and the
  three inert U+FFFD decodes (null, out-of-range, surrogate codepoints).
- `packages/maistro-design/tests` (+7): `test_scan.py` gained
  `TestCssNetworkPrimitiveReview` — four hostile fetch primitives (the
  `@import url(...)` and `@import "..."` forms, `url(javascript:...)`, and
  an out-of-range port that makes `urlsplit().port` raise), the
  allowlisted-`@import` importer view, same-authority path drift against a
  path-scoped allowlist entry, and the fail-closed contract of
  `_pattern_matches` when the regex engine dies mid-scan.
- `packages/hive-conductor/backend/tests` (+0 node IDs):
  `test_renderers_reject_hostile_markup_before_backend_dispatch` now also
  drives `render_to_pptx` and `render_to_docx`, so the boundary calls on
  both sinks are exercised (they run before the optional backends import).

## Grant prune (Quality gate)

`quality/ratchet-authorizations.json`: the `ac-state` grant
`design_coverage@33.9095` (issue #729) was pruned — the gate's own
supersession rule fired, with three independently landed notes each
clearing the floor on their own, and the ratchet message instructed the
prune. No floor was lowered and no new authorization was added; the fold
without the grant stays above the granted value.
