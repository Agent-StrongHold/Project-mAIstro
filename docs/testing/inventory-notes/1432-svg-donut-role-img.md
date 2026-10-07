---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
---
# Issue 1432 - SVG chart named with aria-label but no role=img

UX-audit finding A11Y-11: `SvgDonut.tsx` put `aria-label="Donut chart"` on a
bare `<svg>`. Browsers do not map an unadorned `<svg>` to the image role, so
assistive technology may never expose the name (WCAG 4.1.2 Name, Role, Value).
The fix adds `role="img"` beside the label, matching the pattern
`FixedPageArtifactEditor.tsx` already uses for its chart and diagram svg
templates.

## Testing

The component has no importers (the audit's GLO-02 dead-code note), so no
rendered-page or e2e test can reach it. `test_svg_accessible_names.py` reads
the frontend sources the way `test_csp.py` does:

- `TestTheDonutChart` pins the audited component: its named chart svg must
  carry the `Donut chart` accessible name on an explicit `role="img"`.
- `TestEveryNamedSvgInTheFrontend` generalizes the invariant — every
  `<svg …>` opening tag in `frontend/src` that carries an `aria-label` must
  declare `role="img"`. Tag extraction tracks quotes and brace depth so the
  multi-line interactive-diagram tags (arrow-function handlers containing
  `>`) parse correctly; with the fix reverted the invariant names
  `src/components/SvgDonut.tsx` as the sole offender.

Both tests were run red against the unfixed component (2 failed) and green
after the one-attribute fix.
