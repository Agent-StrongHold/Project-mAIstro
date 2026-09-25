---
inventory-delta:
  packages/maistro-core/tests: +9
  packages/maistro-design/tests: +31
  packages/hive-conductor/backend/tests: +1
---
# Issue 817: Design trust active-markup corpus

Inventory correction: the `packages/hive-conductor/tests/e2e: +1` claim was
removed — the suite inventory counts pytest node IDs and the e2e recipe
collects only Python tests, so a Playwright spec addition (the active-markup
browser corpus in `deck-sanitization.spec.ts`) is not a collectable delta.
The browser coverage itself is documented below and exercised by the Playwright
suite.

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
enforcement. The browser regression also proves ordinary `class` presentation
markup has the same upgrade classification across the browser and Python trust
paths. MathML, which the browser's HTML/SVG allowlist strips as an active element,
is now covered at both boundaries: the shared Warden visual-artifact vocabulary
blocks it before an admin trust recommendation, and the browser regression pins
the same `active-element` review classification.

## Independent verification provenance (auto-817 @ 983fc77)

Executed at head `983fc779cd81cf7f425935bbb0027fe59d1aa419` (develop merge
`8bb344e32b8693574fc0be7a93f86d941616b62c` included), read-only lane:

- `uv run pytest packages/maistro-design/tests packages/hive-conductor/backend/tests/test_design_renderers.py packages/maistro-core/tests/security/warden -q` → 382 passed. Full security suite: 1266 passed, 19 skipped (1 deselected: pre-existing `test_log_redaction.py::test_install_is_idempotent` pytest log-capture interaction; test+impl identical to base, fails in isolation, root cause is pytest `catching_logs` attaching non-redacting capture handlers to non-propagating loggers — out of lane).
- Executed probes: 14-case hostile corpus (MathML, handlers, script SVG, `data:text/html`, CSS `url()`/`image-set`/`@import`, meta refresh, form action, dangerous URLs) returns pre-scan SKULL/`banish`/explicit flags AND output-boundary blocked on every case; clean brief stays T3/`upgrade`. The previously reported `<math><mi>x</mi></math>` → `t3/upgrade/()` parity break does not reproduce.
- `uv run ruff check .` / `ruff format --check .` → pass. CI-exact mypy (`--extra dev` env, nine src trees incl. maistro-design) → 0 issues. `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*'` → rc=0, 1415→1415. `scripts/check-merge-markers.py` → ok. Suite inventory → 13/13 match.
- Playwright `deck-sanitization.spec.ts` executed locally in Chromium: 5/5 passed (payload families, trust recommendations `upgrade`/`review` parity, poster/infographic/flyer preview/edit/export through the shared boundary). Run used a newer cached Chromium via `executablePath` because the pinned `chromium_headless_shell-1223` cannot be downloaded on this OS (ubuntu26.04 unsupported by the local Playwright downloader); functional coverage identical to the CI recipe's harness path.
- bandit Medium+ on core/hive-backend/server: 0.
- **OPEN FINDING (blocking CI gate, introduced by this branch):** the CI `security.yml` SAST command (`uvx semgrep --config p/security-audit ... --error packages/ tests/`) exits 1 with exactly one blocking finding: `typescript.react.security.audit.react-dangerouslysetinnerhtml` at `packages/hive-conductor/frontend/src/lib/visualArtifactRenderer.tsx:381` (`dangerouslySetInnerHTML={{ __html: sanitizeVisualArtifactMarkup(markup) }}`). A/B probe in an isolated git tree with the same rule set: the develop-base `DeckBuilder.tsx` sinks produce 0 findings, the branch renderer file produces the 1 blocking finding, so the base tree was SAST-green and this branch turns the gate red. Repo convention for reviewed sinks is an inline `# nosemgrep: <rule>` annotation with justification (see `routes/containers.py:21`); no such annotation or rule-scoped exclusion exists yet. All other acceptance evidence above is green; this is the sole gap.

## Independent verification round 2 (auto-817 @ 06fd7107)

Re-executed at head `06fd71077312e2de59652ddffc75200b7fda4efa` (delta vs
`983fc779` is docs-only):

- 382 lane tests (`packages/maistro-core/tests/security/warden/`,
  `packages/maistro-design/tests`,
  `packages/hive-conductor/backend/tests/test_design_renderers.py`) pass.
  `ruff check .` / `ruff format --check .` pass. `scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'` → rc=0,
  1415→1415 (prior vulture finding resolved).
- Probe corpus (16 cases): MathML → SKULL/`banish`/`active-element` (the
  originally reported `<math><mi>x</mi></math>` → `t3/upgrade/()` parity break
  does not reproduce at this head); handlers, script SVG, `data:text/html`,
  meta refresh, form action, poster, stylesheet link, entity script,
  lookalike font-CDN authority, prompt injection all SKULL/`banish` with
  explicit flags; inert class markup stays T3/`upgrade`.
- **STILL OPEN — SAST gate red (executed at this head):** the CI-exact
  `uvx semgrep --metrics off --config tools/semgrep/maistro-rules.yaml
  --config p/security-audit --config p/owasp-top-ten --config p/secrets
  --exclude 'packages/hive-conductor/eval' --exclude
  'packages/hive-conductor/cage' --error packages/ tests/` exits 1 with the
  single blocking `typescript.react.security.audit.react-dangerouslysetinnerhtml`
  finding at `packages/hive-conductor/frontend/src/lib/visualArtifactRenderer.tsx:381`.
  The file does not exist at develop base `8bb344e32` (branch-introduced red
  gate). The repo's reviewed-sink convention (`# nosemgrep: <rule> -- reason`,
  cf. `packages/hive-conductor/backend/routes/containers.py:21`) is not applied
  and no rule-scoped exclusion exists.
- **NEW — CSS hex-escape decoder bypass (executed end-to-end at this head):**
  `_CSS_ESCAPE_RE` (`packages/maistro-core/src/maistro/security/normalize.py:35`)
  is a raw string, so `[ \\t\\r\\n\\f]` matches literal backslash + letters
  t/r/n/f instead of tab/CR/LF/FF; the "optional terminator" then consumes the
  letter following the hex digits. `scan_design_text('<div
  style="background:\75rl(https://evil.example/leak)">y</div>')` returns
  `passed=True, flags=()`, and the trust pre-scan records `t3/upgrade/()` for
  the same content — while a CSS parser decodes `\75rl` as `url` and fetches.
  Plain `url(` is blocked at the same boundary, so the escape is a true
  evasion of the AC-3 CSS family. The same probe family bypasses AC-2's
  pre-scan. The branch test corpus only covers the mid-token form `u\72l(`
  (`test_scan.py:62`, `test_design.py:230`, `test_design.py:1266`,
  `test_detector.py:88`); the leading-escape form is covered at no boundary,
  and `deck-sanitization.spec.ts` uses plain `url(`. Because
  `normalize_for_detection` is the shared Warden/Sentinel detection fold, the
  defect is in the shared substrate, not Design-only.

## Independent verification round 3 (auto-817 @ fce0272, repair confirmed)

Re-executed at merge head `fce027262b9d1c5d74b98a2c6329e2da88476767`
(`96e6c4d8e2d5f9b99a7dc51620ae6413d5c916ca` + develop merge `750edd84d`;
`git diff 96e6c4d8..fce02726` touches only CHANGELOG.md and the #1192
pause-reason-waker content — zero security-surface drift), read-only lane:

- 392 lane tests pass: `uv run pytest packages/maistro-design/tests
  packages/maistro-core/tests/security/warden -q` → 385 passed;
  `packages/hive-conductor/backend/tests/test_design_renderers.py` → 7
  passed. `ruff check .` / `ruff format --check .` → pass. Suite inventory →
  maistro-design 309, maistro-core 10786, hive-conductor backend 2655, all
  matching.
- **Round-2 finding 1 (CSS hex-escape bypass) closed:** probes execute the
  leading-escape spellings at both boundaries —
  `scan_design_text('<div style="background:\\75rl(http://evil.example/x)">y</div>')`
  and the `\000075rl(` form both return `passed=False` with
  `css-network-or-code`; the trust pre-scan records SKULL/`banish` with
  shared output-boundary flags for both.
- **Round-2 finding 2 (SAST gate red) closed:** the CI-exact semgrep command
  (`--config tools/semgrep/maistro-rules.yaml --config p/security-audit
  --config p/owasp-top-ten --config p/secrets --exclude eval --exclude cage
  --error packages/ tests/`) exits 0 with 0 findings across 1888 files; the
  reviewed sink at `visualArtifactRenderer.tsx` carries the repo-standard
  `// nosemgrep: typescript.react.security.audit.react-dangerouslysetinnerhtml
  -- justification` annotation.
- Probe corpora: 10-case pre-scan corpus through `scan_and_record` (script,
  MathML, `onerror=`, SVG `onload`, `data:text/html` href, CSS `url()`,
  leading-escape CSS, prompt injection, foreignObject script, clean brief) →
  9× SKULL/`banish` with explicit flags, clean brief stays T3/`upgrade` with
  `()` flags; 20-case output corpus (handlers incl. `onpointerenter`,
  `<body onload>`, script SVG, `use`/`image` data URLs, `animate` href
  javascript:, `data:text/html` iframe/link, `@import`, `behavior:`,
  `-moz-binding:`, `expression(`, both leading-escape CSS forms, prompt
  injection) → all blocked; 3 inert presentation cases pass.
- Browser corpus executed in the `auto817-playwright` Playwright image with
  the four worktree diff-surface frontend files bind-mounted over the baked
  copies: `deck-sanitization.spec.ts` 5/5 passed, including the `\75rl(`
  fail-closed sanitize + `css-network-or-code` scan-reason assertions and the
  `recommendVisualArtifactTrust` parity block (MathML → `review`).
- Gates outside the lane's diff remain red but are pre-existing at develop
  base `750edd84d`, proven by scan-diff, not assumed: vulture rc=1 — the
  ledger is byte-identical between base and head and no NEW-debt file other
  than `design_render.py` is touched by this branch; that file's three
  identities (`_render_cache`, `render_to_pptx`, `slide_width`) already exist
  at base (base lines 28/98/115), while the branch's own additions
  (`_enforce_output_boundary`) are called at all four renderer entry points.
  mypy → 11 errors, none introduced: `design_render.py`'s 4 (weasyprint/docx
  import stubs, `Returning Any`) reproduce identically at base shifted by the
  branch's +13 lines; the other 7 sit in files this branch never touched
  (`cli/_builders_tui.py`, `cli/_install.py`, `engine.py`).
- Closure-keyword review: no `fixes/closes/resolves #N` trailer in any commit
  subject/body between `750edd84d` and `fce027262`; PR #1389 body says only
  "Refs #817" and remains draft.

## Independent verification round 4 (auto-817 @ d39b0de, all four prior findings re-probed)

Re-executed at the lane's exact starting head `d39b0dea982ee7b1960b30cdca6e2fd19cfaea88`.
No production file changed this round; this is fresh executed evidence only.

- **L817 probe (round-1 finding) re-executed and closed:**
  `scan_and_record("<math><mi>x</mi></math>", ...)` now returns
  `tier=skull, recommendation=banish,
  flags=("content: visual artifact active-element",), confidence=0.9` —
  the exact classification real Chromium reports for the same markup
  (blocked, `active-element`), so AC-2/AC-4 parity holds in both
  directions. Full 7-case probe: script/`onerror`/`data:text/html`/CSS
  `url()`/leading-escape `\75rl(` all SKULL/`banish` with explicit shared
  flags; clean brief stays T3/`upgrade` with `()` flags.
- **SAST gate re-executed:** CI-exact semgrep (all four configs, `--error
  packages/ tests/`) exits 0 — 364 rules over 1888 files, 0 findings;
  targeted re-run over `frontend/src/lib/` (125 rules) also 0 findings.
  bandit Medium+ strict gate: 0.
- **Vulture gate re-executed:** CI-exact scope
  (`packages/*/src --min-confidence 60 --exclude '*/third_party/*'`) exits 0:
  1415 reviewed identities -> 1415 findings vs base `750edd84d`.
- **Static/regression battery:** `ruff check .` + `ruff format --check .`
  clean on tracked files; mypy (AGENTS.md 712-file scope) clean;
  `check-suite-inventory.py` ok (13/13 suites);
  `packages/maistro-design/tests` 309 passed;
  `packages/maistro-core/tests` 10130 passed / 654 skipped (DB-dependent).
- **Browser corpus re-executed against the current sources:** rebuilt the
  Playwright image from this worktree (`auto817-playwright-r4`, npm layer
  cached) with the live `visualArtifactRenderer.tsx` bind-mounted read-only
  over the baked copy; `deck-sanitization.spec.ts` 5/5 passed in Chromium,
  including the MathML `active-element` scan-reason, the
  `recommendVisualArtifactTrust` parity block (MathML -> `review`), and the
  `\75rl(` fail-closed assertions.
- **One pre-existing red outside this issue, recorded not repaired:**
  `maistro-core/tests/security/test_log_redaction.py::test_install_is_idempotent`
  fails under pytest 9.1.1's logging plugin (assert 2 == 0) and passes with
  `-p no:logging`. The test and `log_redaction.py` are byte-identical to
  develop base `60862b6c`; this branch's only lock delta is hive-conductor
  gaining `cryptography`. An isolated probe of `install_log_redaction`
  outside that suite confirms the production function is idempotent, so the
  defect is test/plugin interaction drift, not #817 scope.
- The three scratch probe scripts left untracked by the failed prior run
  (`repro.py`, `repro_v2.py`, `test_scan.py`) were preserved by moving them
  out of the worktree to the job directory; their assertions are superseded
  by the committed corpora above.

## Independent verification round 5 (auto-817 @ b18cd9b7, final lane head)

Re-executed at the lane's exact final head `b18cd9b78f1d2952121043f2e89ee117d81f67bf`
(f9ec5bf09 union repair + develop merge `03c8ba83a`). Read-only probes; the only
tracked change in this round is this note.

- **Lane pytest:** `uv run pytest packages/maistro-design/tests
  packages/maistro-core/tests/security/warden
  packages/hive-conductor/backend/tests/test_design_renderers.py -q` → 393
  passed.
- **Probe corpora re-executed at this head:** 14-case `scan_and_record` corpus
  (MathML, script, handler attrs, SVG onload, `javascript:`, `data:text/html`,
  CSS `url()`/`@import`, foreignObject script, meta refresh,
  `annotation-xml`) → all SKULL/`banish`/0.90 with shared visual-artifact
  flags; clean brief stays T3/`upgrade`/`()`. 16-case `scan_design_text`
  output-boundary corpus (handlers incl. `<body onload>`, script-capable SVG,
  `use`/`image`/iframe `data:text/html`, CSS `url()`/`@import`/`image-set`/
  `behavior:`/`-moz-binding:`, leading- and mid-token hex escapes, prompt
  injection, `javascript:`, MathML) → all blocked; 3 inert presentation cases
  pass. `<style>` blocks on BOTH sides (pre-scan and Chromium allowlist), so
  the parity direction required by AC-4 holds.
- **SAST gate re-executed CI-exact** (`uvx semgrep --metrics off --config
  tools/semgrep/maistro-rules.yaml --config p/security-audit --config
  p/owasp-top-ten --config p/secrets --exclude eval --exclude cage --error
  packages/ tests/`) → rc=0, 364 rules / 1892 files / 0 findings; the reviewed
  sink annotation at `visualArtifactRenderer.tsx` holds.
- **Vulture gate re-executed CI-exact** (`scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'`) → rc=0,
  1415→1415 vs base `03c8ba83a`.
- **Browser corpus re-executed in Chromium** (image `auto817-playwright-r4`,
  live `visualArtifactRenderer.tsx`, `deckSanitizer.ts`, `DeckBuilder.tsx`,
  `FixedPageArtifactEditor.tsx`, and the 8-test spec bind-mounted over the
  baked copies): `deck-sanitization.spec.ts` 8/8 passed, including the
  mutation/encoded/SVG/CSS payload families, CSS-obfuscation and active-SVG
  fail-closed assertions, and the `recommendVisualArtifactTrust` parity block
  (MathML → `review`).
- **Static gates:** `ruff check .` and `ruff format --check .` clean;
  `check-merge-markers.py` ok; suite inventory ok for maistro-design (310),
  maistro-core, and hive-conductor backend.
- **Scratch salvage preserved:** the failed prior run left two untracked
  scratch files (`reproduce_issue_817.py`, `packages/maistro-design/tests/
  test_repro_817.py`). The latter silently added +3 node IDs to the
  maistro-design suite (313 collected vs recorded 310 → `check-suite-inventory`
  DRIFT, and ruff I001/F401 against both files). Their assertions (MathML/
  script/data-URL → SKULL with flags) are strictly subsumed by the committed
  `test_trust_prescan.py` corpus, which pins flags to the exact shared
  output-boundary verdict. Both files were preserved (not deleted) by moving
  them to the job directory's `salvaged-scratch/`, matching the round-4
  precedent; no production or test file changed this round.
