---
inventory-delta:
  packages/maistro-design/tests: +1
---

# 768-self-closing-dispatch-regression

CI-repair follow-up for #768 (exact-debt-ledger): the vulture per-identity
ledger flagged `scan.py::handle_startendtag` and `scan.py::handle_starttag`
(60% confidence) as unbanked identities. The repair removes the genuinely
redundant override and references the remaining parser-protocol callback
in-module (mirroring `packages/maistro-core/src/_vulture_whitelist.py`), so no
ledger amendment is needed: 1414 reviewed identities -> 1414 findings.

## Why the override was redundant

`html.parser.HTMLParser.handle_startendtag`'s stdlib default already delegates
to `handle_starttag(tag, attrs)` with the identical argument list, and
`_VisualArtifactScanner` does not override `handle_endtag`. Removing the
override is behavior-preserving: every self-closing tag goes through the same
`_check_tag`/`_check_attribute` walk exactly once.

## New test (+1 in test_scan.py)

`test_self_closing_tags_dispatch_through_the_same_start_tag_checks` feeds
`<img src="data:text/html,x" onerror="pwn()"/>` and asserts both
`event-handler` and `dangerous-url`. If a future edit re-introduces a
`handle_startendtag` override that drops (or duplicates) the allowlist walk,
hostile self-closing markup would slip past the #817 trust pre-scan while the
browser boundary still blocks it — this test turns that drift into a red unit
test instead of a silent classification gap.
