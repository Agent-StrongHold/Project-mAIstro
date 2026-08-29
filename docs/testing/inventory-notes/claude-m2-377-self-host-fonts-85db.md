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
node:** `packages/hive-conductor/tests/e2e/offline-assets.spec.ts` is the check
the issue's definition of done actually asks for. It aborts every request that
would leave the app's origin — the air gap, applied at the browser — then asks
the app to load and both families to resolve. Asserting "the `<link>` tags are
gone" would prove nothing durable; the next import, icon set or analytics
snippet puts the dependency straight back, and only a test that cuts the
network notices.

Two things about it were measured rather than assumed. It lives in
`tests/e2e/`, not `frontend/e2e/`, because `frontend/e2e/` is run by no
workflow — a spec placed there would never have executed, which is a worse
outcome than not writing it. And it reads the face out of `document.fonts` and
checks its status instead of calling `document.fonts.check()`: run against a
build with no `@font-face` at all, `check()` reported an invented family as
available, because a CSS font shorthand always resolves to something. The
assertion now fails when asked for a family nothing ships, which was confirmed
by asking for one.
