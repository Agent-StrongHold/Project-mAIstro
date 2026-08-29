---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
---
# claude-m2-377-self-host-fonts-85db

`frontend/index.html` opened every page with three `<link>` tags to Google
Fonts. That put a CDN in the critical path of a product designed to run on a
mini-PC with no guaranteed internet, handed every visitor's IP to a third
party, and was the sole reason the Content-Security-Policy had any third-party
origin at all. One of the three families, Caveat, was fetched on every page
load and referenced by nothing in the tree.

**`packages/hive-conductor/backend/tests/test_csp.py` (+2 net; +3 added, −1
replaced)**:

- `test_the_production_policy_names_no_third_party_origin` **replaces**
  `test_the_only_third_party_origins_are_the_font_hosts_index_html_names`. It
  keeps that test's shape — both sets still derived, one by reading
  `index.html` and one by reading the policy — and now asserts both are empty.
  Deriving rather than listing is the point: the failure this guards against is
  the *next* CDN, not the last one.
- `test_the_typefaces_the_themes_ask_for_are_shipped_with_the_app` catches the
  quiet failure. A CSS stack naming a family nothing serves falls through to
  the system font; the page renders, the screenshot looks plausible, and the
  design intent is gone with no test failing. Each self-hosted family is
  asserted against the dependency in `package.json` that ships it.
- `test_nothing_imports_a_typeface_over_the_network` closes the other door.
  `@import url(https://…)` inside a stylesheet reaches a font host without ever
  appearing in `index.html`, so the origin test above could not see it.

**Not counted here, because it is a Playwright spec rather than a pytest
node:** `frontend/e2e/offline.spec.ts` is the check the issue's definition of
done actually asks for. It aborts every request that would leave the app's
origin — the air gap, applied at the browser — then asks the page to render and
both families to resolve through `document.fonts.check`. Asserting "the `<link>`
tags are gone" would prove nothing durable; the next import, icon set or
analytics snippet puts the dependency straight back, and only a test that cuts
the network notices.
