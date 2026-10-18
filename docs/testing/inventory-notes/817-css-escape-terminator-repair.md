---
inventory-delta:
  packages/maistro-core/tests: +5
  packages/maistro-design/tests: +5
---
# 817-css-escape-terminator-repair

Repair round for #817 (verification found the CSS hex-escape decoder reading a
different token than a CSS parser). Nothing was removed or moved; every change
is an addition.

## Production fix

`packages/maistro-core/src/maistro/security/normalize.py` — `_CSS_ESCAPE_RE`
was a raw string with doubled backslashes, so the optional whitespace
terminator class `[ \\t\\r\\n\\f]` matched the literal letters t/r/n/f instead
of tab/CR/LF/FF. On the leading-escape spelling `\75rl(` the class consumed
the `r` as the "terminator", the detection view decoded `ul(` where a CSS
parser reads `url(`, and fetchable CSS slipped past Warden, the Design output
boundary, and the trust pre-scan (which then recommended `upgrade` on it).
The classes are single-escaped now; a comment in the file pins why.

The browser half of the shared #768 boundary
(`visualArtifactRenderer.tsx`) was probed in Chromium and does not have the
bypass: the CSSOM decodes `\75rl(` to a `url(...)` value before
`NETWORK_OR_CODE_CSS` matches, so the TS sanitizer blocked all spellings without a change. The reviewed React sink otherwise
gained only the repo-standard `// nosemgrep: <rule> -- justification`
annotation for
the CI semgrep rule that cannot see the sanitizer call in the same expression
(rc 1 → 0 on the CI-exact command).

## Test additions (+5 / +5)

`packages/maistro-core/tests/security/warden/test_detector.py` (+5):

- 1 parametrized case on
  `test_scan_layer1_blocks_active_markup`: the leading-escape
  `<style>.x { background: \75rl(...) }</style>` payload is blocked by a full
  `Warden().scan`.
- 1 new parametrized test, `test_detection_view_decodes_css_hex_escapes_like_a_css_parser`,
  with 4 cases pinning the decoder's exact output: leading-escape `\75rl(`,
  mid-token `u\72l(`, whitespace-terminated `\75 rl(`, and a hex escape at
  end of string. This is the regression test for the bypass itself.

`packages/maistro-design/tests` (+5):

- `test_scan.py` (+1) and `test_design.py` (+2, one hostile-output corpus and
  one trust pre-scan corpus): the leading-escape spelling joins the hostile
  corpora, so the final output boundary and the shipped
  `build_multimodal_output` path both reject it.
- `test_trust_prescan.py` (+2, the corpus feeds two parametrized tests): the
  pre-scan must classify `\75rl(` SKULL/banish with the shared
  output-boundary flags — the AC-2 direction of the original bypass (it used
  to come back T3/`upgrade` with no flags).

The browser corpus (`packages/hive-conductor/tests/e2e/deck-sanitization.spec.ts`)
also gained the leading-escape payload in both the fail-closed sanitize list
and the scan-reason assertions. That suite's collected count is unchanged (no
new test functions), so no delta is recorded for it here. Executed in
Chromium (Playwright image, harness bundling the worktree's real TSX): 5/5
pass with the new payloads.

## Environment notes for future verifiers of this worktree

- `packages/hive-conductor/frontend/node_modules` (gitignored, untracked,
  appeared after the last recorded green run) shadows the Playwright harness's
  `/tests/node_modules`, so the harness bundle gets two React copies and
  DeckBuilder dies on `Cannot read properties of null (reading 'useState')`
  before the first assertion. Mounting an empty dir over it makes the suite
  green; the directory itself was left in place (it is a build artifact, not
  work) and is never copied into the CI image.
- `scripts/check-vulture-baseline.py` exits 1 at the clean starting head too
  (verified byte-identical output with and without this change), so its debt
  is pre-existing drift, not introduced here.
