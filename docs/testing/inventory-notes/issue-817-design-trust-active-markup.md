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

## Independent verification round 6 (auto-817 @ a0709b0f, verifier lane)

Re-executed at the lane's exact head `a0709b0f8a8a23fac47218e583476f1123914202`
(unchanged since round 5). All evidence below executed fresh in this round;
read-only probes plus this note.

- **Lane pytest re-executed:** `uv run pytest
  packages/maistro-core/tests/security/warden/test_detector.py
  packages/maistro-core/tests/security/warden/test_visual_artifact_vocabulary.py
  packages/maistro-design/tests/test_design.py
  packages/maistro-design/tests/test_scan.py
  packages/maistro-design/tests/test_trust_prescan.py -q` → 217 passed.
  `packages/hive-conductor/backend/tests/test_design_renderers.py` → 7 passed.
- **Pre-scan probes re-executed** (`scan_and_record`, review-queue records
  inspected): `<math><mi>x</mi></math>` → `tier=skull, rec=banish, conf=0.9,
  flags=("content: visual artifact active-element",)` — the round-1 parity
  break does not reproduce. script, handler attr, `data:text/html` href,
  CSS `url()`, leading-escape `\75rl(`, SVG script, `@import`, `behavior:` →
  all `skull/banish/0.9` with flags **exactly equal** to
  `scan_blocking_patterns(..., visual_artifact=True)` on the same content.
  Clean brief → `t3/upgrade/()`.
- **Output-boundary probes re-executed** (`scan_design_text`): 15 hostile
  AC-3 families blocked (handler attrs incl. `<body onload>`, script SVG,
  `use`/`img` data URLs, `data:text/html` iframe, CSS `url()`/`@import`/
  `image-set`/`behavior:`/`-moz-binding:`/`expression(`, both hex-escape
  spellings, MathML); clean HTML and clean CSS pass.
- **Vocabulary parity (AC-4) inspected:** `VISUAL_ARTIFACT_PATTERNS` reasons
  are unpacked from `VISUAL_ARTIFACT_BLOCK_REASONS`
  (`patterns.py:81-100`); the TSX boundary declares the identical 4-name
  tuple (`visualArtifactRenderer.tsx:232-238`); the
  `test_visual_artifact_vocabulary.py` tests pin the derivation and that the
  scanner emits only declared reasons. No second scanner exists in Design —
  `scan.py` imports the Warden pattern tables (#817 stop condition holds).
- **Chromium corpus re-executed against live sources:** `deck-sanitization.spec.ts`
  via local esbuild harness (`E2E_SRC_ROOT`/`NODE_PATH` at this worktree, no
  image rebuild) → **8/8 passed**, including payload families, CSS
  obfuscation/active-SVG fail-closed, and the `recommendVisualArtifactTrust`
  parity block (MathML → `review`).
- **SAST gate re-executed CI-exact** (`uvx semgrep --metrics off --config
  tools/semgrep/maistro-rules.yaml --config p/security-audit --config
  p/owasp-top-ten --config p/secrets --exclude eval --exclude cage --error
  packages/ tests/`, semgrep 1.178.0) → **rc=0, 364 rules / 1892 files /
  0 findings**. Reviewed-sink annotation holds at
  `visualArtifactRenderer.tsx:394`.
- **Vulture gate re-executed CI-exact** (`scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'`) →
  **rc=0, 1415 reviewed identities → 1415 findings** vs base `03c8ba83a`.
  Neither prior #817 debt identity (`patterns.py`
  `VISUAL_ARTIFACT_BLOCK_REASONS`, `container.py:415`) appears in the scan.
  Residual, non-#817, recorded not repaired: a bare-scope invocation
  (`packages tests`, wider than CI) exits 1 with 1445 findings vs the same
  1415-identity ledger; the identical scan at base `03c8ba83a` reports 1447
  (temp worktree probe, removed after measurement), so the drift is
  pre-existing ledger/environment churn in categories dominated by files this
  branch never touched — the branch is net-negative (1447 → 1445).
- **Static gates re-executed:** `uv run ruff check .` → clean;
  `uv run ruff format --check .` → 2543 files already formatted.
- **Closure-keyword review re-executed:** `git log 03c8ba83..HEAD` subjects
  and bodies contain no `fixes/closes/resolves #N`; PR #1389 body says only
  "Refs #817" and remains draft — no premature issue-closure action.

## Repair round 7 (auto-817 @ 23fefb6a7, writer lane): develop-sync merge + fresh re-validation

Resolved the previous block ("launch/preflight: Hosted PR snapshot incomplete
or not the review head"): the branch was 1 commit behind `origin/develop`
(`5eeac0734`, #1464 compliance gating — disjoint file set from every #817
surface). Executed `git merge origin/develop` → merge commit `23fefb6a7`,
**zero conflicts** (verified: the develop commit touches only
`.github/`, `COMPLIANCE.md`, `docs/ci/`, `quality/`, `scripts/check-compliance.py`,
`scripts/produce-compliance-evidence.py`, `scripts/check-ratchet-provenance.py`,
`tests/test_check_compliance.py`, and #362 inventory notes). The branch is now
a strict descendant of `origin/develop`.

Fresh evidence executed at the merged head `23fefb6a7`:

- **Pre-scan probe re-run:** `<math><mi>x</mi></math>` → `tier=skull,
  rec=banish, conf=0.9, flags=("content: visual artifact active-element",)`;
  script/handler/iframe/SVG-script/`data:text/html`/CSS-`url()`/prompt-injection
  cases → all `skull/banish` with explicit shared-vocabulary flags; benign
  paragraph → `t3/upgrade/()`. Round-1 finding 1 stays fixed at the merge head.
- **Lane pytest:** `packages/maistro-core/tests/security` +
  `packages/maistro-design/tests` → 1587 passed, 19 skipped, **1 failed:
  `test_log_redaction.py::test_install_is_idempotent`** — proven pre-existing
  and unrelated: those files have zero diff vs `origin/develop` in this branch
  (no commit touches them), and the test fails in isolation on the canonical
  clone at unrelated head `57ddca502`. Not an #817 regression.
- `packages/maistro-design/tests/test_trust_prescan.py` +
  `test_scan.py` + `packages/maistro-core/tests/security/warden` → 125 passed
  (27 hostile/parity pre-scan cases incl. MathML and `\75rl(`; hostile
  active-markup corpus; vocabulary-lockstep tests).
- `packages/hive-conductor/backend/tests/test_design_renderers.py` → 7 passed.
- **Chromium corpus re-run post-merge** (`deck-sanitization.spec.ts`, local
  esbuild harness at worktree sources, @playwright/test 1.60.0) → **8/8
  passed**, incl. mutation/encoded/SVG/CSS families fail-closed, block
  reasons from the shared 4-name vocabulary, and `recommend('<math><mi>x</mi></math>')`
  → `"review"`.
- **SAST gate (CI-exact)** → rc=0, 364 rules / 1892 files / 0 findings at the
  merge head; the single reviewed sink keeps its justified `nosemgrep`
  annotation (`visualArtifactRenderer.tsx:394`).
- **Vulture ledger gate (CI-exact)** → rc=0, 1415 reviewed identities →
  1415 findings, candidate `23fefb6a7` vs base `5eeac0734`. No ledger edit
  needed this round.
- **Static gates:** `uv run ruff check .` clean; `uv run ruff format --check .`
  → 2546 files already formatted.
- **Post-merge develop gates:** `scripts/check-compliance.py` at rest → exit 0
  ("compliance registry and COMPLIANCE.md are valid");
  `scripts/check-ratchet-provenance.py` → exit 0 (37 consumers have
  provenance, 0 lifecycle violations); `tests/test_check_compliance.py` →
  97 passed.
- **Frontend typecheck:** `tsc -p tsconfig.json --noEmit` → exit 0.
- **mypy:** the AGENTS.md battery reports 7 errors, all pre-existing /
  environmental (missing `maistro_bootstrap` editable, `maistro_canvas`
  py.typed, unchanged `engine.py:148` unused-ignore); none in the five files
  this lane changed, which remain mypy-clean.

No production or test file changed this round (validation + merge only);
no new tests added, so no inventory-delta change.

## Independent verification round 8 (auto-817 @ 8b586577a, verifier lane)

Re-executed at the lane's exact head `8b586577a30e236dc6d5125966679efed2ad335d`
(develop base `2c8022fe8` merged; `git diff 23fefb6a7..8b586577a` touches only
`.github/workflows/{ci,release,security}.yml` action-version bumps and this
note — zero production-code drift vs the round-7 evidence head). All evidence
below executed fresh in this round; read-only probes plus this note.

- **Lane pytest re-executed:** `uv run pytest
  packages/maistro-core/tests/security/warden/test_detector.py
  packages/maistro-core/tests/security/warden/test_visual_artifact_vocabulary.py
  packages/maistro-design/tests/test_design.py
  packages/maistro-design/tests/test_scan.py
  packages/maistro-design/tests/test_trust_prescan.py -q` → **217 passed**.
  `packages/hive-conductor/backend/tests/test_design_renderers.py` → 7 passed.
  `uv run ruff check .` → clean. Suite inventory ok for hive-conductor
  backend (2722), maistro-core (10908), maistro-design (310).
- **Pre-scan probe re-executed** (`scan_and_record` + review-queue records):
  `<math><mi>x</mi></math>` → `tier=skull, rec=banish, conf=0.9,
  flags=("content: visual artifact active-element",)` (round-1 finding stays
  fixed); `<script>`, handler attr, `data:text/html` iframe, CSS `url()` →
  all `skull/banish` with explicit shared flags; clean paragraph →
  `t3/upgrade/()`.
- **Chromium corpus re-executed at this head** (image `auto817-playwright-r4`,
  live worktree `visualArtifactRenderer.tsx`, `deckSanitizer.ts`,
  `DeckBuilder.tsx`, `DesignStudio.tsx`, `FixedPageArtifactEditor.tsx` and the
  spec bind-mounted read-only): `deck-sanitization.spec.ts` → **8/8 passed**
  (payload families, CSS obfuscation/active SVG fail-closed, trust-recommendation
  parity).
- **SAST gate re-executed** (`uvx semgrep --config tools/semgrep/maistro-rules.yaml
  --config p/security-audit --error packages/hive-conductor/frontend/src/lib/`)
  → rc=0, 22 rules / 10 files / **0 findings**; the reviewed-sink
  `nosemgrep` annotation at `visualArtifactRenderer.tsx:394` holds.
- **Vulture gate re-executed** (`scripts/check-vulture-baseline.py`) → rc=0;
  the prior unapproved-debt finding does not reproduce.
- **Closure-keyword review re-executed:** `git log 2c8022fe8..8b586577a`
  (38 commits) contains no `fixes/closes/resolves #N`; PR #1389 body says
  only "Refs #817", remains draft, and live `headRefOid` equals this head
  (the round-7 "snapshot not the review head" block is resolved).

## Independent verification round 9 (auto-817 @ c23e4ddaaf, verifier lane)

Re-executed at the lane's exact head `c23e4ddaaf652a46282e63ee95633ff274d7bcad`
(manifest head == live PR #1389 `headRefOid`, confirmed via read-only
`gh pr view` refresh; `git diff 8b586577a..c23e4ddaaf` touches only this note —
zero production/test drift vs the round-8 evidence head). All evidence below
was executed fresh in this round, before this note was committed.

- **Deterministic driver checks inspected:** job
  `c98297b81ab64bd9a18cb4d01919c889` check-0..7 all rc=0 (`uv sync --locked`,
  `ruff check .`, `ruff format --check .` → 2546 files, 217 lane tests, 7
  backend renderer tests, suite inventories ok: hive-conductor backend 2722,
  maistro-core 10908, maistro-design 310).
- **Lane pytest re-executed by this round:** 217 passed (warden detector +
  visual-artifact vocabulary + design/scan/trust-prescan);
  `test_design_renderers.py` → 7 passed.
- **Pre-scan probe re-executed:** `scan_and_record('<math><mi>x</mi></math>')`
  → `skull/banish/0.9/('content: visual artifact active-element',)`; `<script>`,
  event-handler attr, `data:text/html`, CSS `url()`, CSS `\75rl(` escape → all
  `skull/banish` with explicit shared flags; benign paragraph →
  `t3/upgrade/()` and output boundary passes. Pre-scan flags ≡ output-boundary
  flags on every probe (AC-4).
- **Chromium corpus re-executed by this round** (image `auto817-playwright-r4`,
  live worktree sources + spec bind-mounted read-only):
  `deck-sanitization.spec.ts` → **8/8 passed (3.0s)**, including the MathML
  cases at spec lines 359/392/412 (`<math><mi>x</mi></math>` blocked and
  `recommend == "review"`) and attacker-server request counts of zero.
- **Vulture gate:** CI-exact argv
  `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` → **rc=0** (1415 → 1415 identities, base
  `2c8022fe` → candidate `c23e4ddaaf`). Observation (not a branch regression):
  the *bare* default invocation (`packages tests`) exits 1 with ~30 net
  scan-vs-ledger drift that reproduces identically at the base tree — a
  base-scan diff showed **0 HEAD-only identities** and 2 HEAD-removed
  (`render_to_pdf` methods); the enforced CI gate is the scoped invocation
  (workflows `vulture-ratchet.yml:82`, `quality.yml:812`), and hosted
  `exact-debt-ledger` SUCCESS agrees.
- **Closure-keyword review re-executed:** `git log 2c8022fe8..c23e4ddaaf`
  contains no `fixes/closes/resolves #N`; live PR #1389 body says only
  "Refs #817", draft, `headRefOid == c23e4ddaaf` (round-7 "snapshot not the
  review head" block stays resolved).
- **Hosted CI:** multiple checks IN_PROGRESS and `gates-ran` PENDING at review
  time → hosted CI UNVERIFIED per contract (local evidence stands on its own);
  one empty-workflow `devskim` FAILURE coexists with a successful DevSkim
  workflow run (draft-PR noise, no local correlate).

## Independent verification round 10 (auto-817 @ 0c843db29, verifier+writer lane)

Re-executed at the lane's exact head `0c843db29b8b9daab673512b1bcba04c55e875a4`
(the manifest/job head; this resolves the prior "verification worktree changed;
evidence rejected" block — round-9 evidence had been minted at `c23e4ddaaf`,
and the only delta is this lane's own docs commit). `git diff c23e4ddaaf..HEAD`
touches only this note. All evidence below was executed fresh in this round,
before this note was committed. The prior run's job directory contains no
check-*.log artifacts (driver died on a provider timeout with `checks: []`),
so every deterministic check was re-executed here.

- **Lane pytest:** `uv run pytest packages/maistro-design/tests
  packages/maistro-core/tests/security/warden -q` → **386 passed**.
  `packages/hive-conductor/backend/tests/test_design_renderers.py` → 7 passed.
  Full `packages/maistro-core/tests/security` → 1277 passed, 19 skipped,
  1 failed — `test_log_redaction.py::test_install_is_idempotent`, proven
  pre-existing and out-of-lane this round by diff evidence, not assumption:
  the test, `log_redaction.py`, both conftests, `pyproject.toml`, and
  `uv.lock` are byte-identical between `origin/develop` and HEAD (empty
  `git diff`), and an instrumented run traced the mechanism — pytest 9's
  logging plugin attaches two `LogCaptureHandler`s to the non-propagating
  `maistro.test.redaction` logger between fixture install and test body, so
  the second `install_log_redaction` call wraps them and returns 2 ≠ 0 while
  the production function returns 0 in a bare interpreter.
- **Pre-scan probes re-executed via `scan_and_record` + review-queue records:**
  `<math><mi>x</mi></math>` → `tier=skull, rec=banish, conf=0.9,
  flags=("content: visual artifact active-element",)` (round-1 parity break
  stays fixed); `<div onclick=…>` → active-markup event-handler +
  `visual artifact event-handler`; `<a href="data:text/html,…">` →
  dangerous-resource/data-URL + `active-element`/`dangerous-url`;
  CSS `url()` → `css-network-or-code`; prompt injection →
  instruction-override + heuristic flag. Clean brief and inert
  `class="marketing-copy"` prose → `t3/upgrade/()`.
- **Output-boundary probes re-executed via `scan_design_text` (AC-3):** 8/8
  hostile families blocked — handler attr, script SVG, `onerror`,
  `data:text/html` iframe, CSS `url()`, leading-escape `\75rl(`, MathML,
  `@import` stylesheet.
- **Chromium corpus re-executed by this round** (local esbuild harness, no
  image rebuild: `E2E_SRC_ROOT=<worktree>/packages/hive-conductor`,
  `E2E_NODE_PATHS=<worktree>/packages/hive-conductor/frontend/node_modules`,
  `NODE_PATH` same, @playwright/test 1.60.0, cached Chromium):
  `deck-sanitization.spec.ts` → **8/8 passed (3.1s)**, including the MathML
  `active-element` scan-reason assertions, `recommend('<math><mi>x</mi></math>')
  → `"review"` parity block, the `\75rl(` fail-closed assertions, and
  zero attacker-server requests.
- **SAST gate re-executed CI-exact** (`uvx semgrep --metrics off --config
  tools/semgrep/maistro-rules.yaml --config p/security-audit --config
  p/owasp-top-ten --config p/secrets --exclude eval --exclude cage --error
  packages/ tests/`, semgrep 1.178.0) → **rc=0, 364 rules / 1892 files /
  0 findings**. A targeted run (custom + p/security-audit) over the four
  surface frontend files also returned 0 findings; the reviewed-sink
  `nosemgrep` annotation at `visualArtifactRenderer.tsx:394` holds.
- **Vulture gate re-executed CI-exact** (`scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'`) →
  **rc=0, 1415 reviewed identities → 1415 findings**, candidate `0c843db29b8b`
  vs base `2c8022fe81c4`. Neither prior #817 debt identity appears.
- **Static gates re-executed:** `uv run ruff check .` → clean;
  `uv run ruff format --check .` → 2546 files already formatted;
  `scripts/check-suite-inventory.py` → 13/13 suites match (hive-conductor
  e2e 23 included); **mypy AGENTS.md battery extended with
  `packages/maistro-design/src` → `Success: no issues found in 731 source
  files`** (round-7's seven pre-existing environmental errors are gone at
  this head). Workspace `uv sync --locked --extra dev` re-ran clean in the
  fresh worktree venv before any probe.
- **Closure-keyword review re-executed:** `git log 2c8022fe8..HEAD` contains
  no `fixes/closes/resolves #N` — no premature issue-closure action.

No production or test file changed this round (fresh validation evidence
only); no new tests added, so no inventory-delta change.

## Independent verification round 11 (auto-817 @ 14cd6c89, verifier+writer lane)

Re-executed at the lane's exact manifest head
`14cd6c89f77414fe3bf5a80f4648d30cae5dcdbc` (develop merge `b906cc577` included;
this resolves the prior "verification worktree changed; evidence rejected"
block). `git diff 0c843db29..HEAD -- <lane surfaces>` is empty, so round-10
evidence carries over; everything below was additionally executed fresh at
this head, before this note was committed.

- **Lane pytest re-executed:** warden detector + vocabulary + design
  test_design/test_scan/test_trust_prescan → **217 passed**;
  `packages/hive-conductor/backend/tests/test_design_renderers.py` → **7
  passed**. `ruff check .` → clean; `ruff format --check .` → 2556 files
  formatted. Suite inventory → maistro-design 310, maistro-core 11000,
  hive-conductor backend 2766, all match.
- **Pre-scan probes re-executed at this head:** `<math><mi>x</mi></math>` →
  `skull/banish`, flag `visual artifact active-element`; `<script>`,
  `onerror`, script-SVG, `data:text/html`, CSS `url()`, `\75rl(`, meta
  refresh, `foreignObject` iframe, prompt injection → all `skull/banish` with
  explicit shared flags; clean brief → `t3/upgrade/()`. Non-heuristic
  pre-scan flags == `scan_blocking_patterns(..., visual_artifact=True)`
  verdict on every probe (AC-4 parity), and `upgrade` only when the boundary
  passes (AC-2).
- **Chromium corpus re-executed at this head** (isolated /tmp esbuild bundle
  of the real `visualArtifactRenderer.tsx` + cached Chromium via
  playwright-core): 10-case corpus — all hostile families `blocked=true`
  with declared `VISUAL_ARTIFACT_BLOCK_REASONS` reasons, payloads stripped
  (`<math>`/`<script>`/`<img>`/`<a data:text/html>`/`<style>` sanitize to
  empty/neutral), zero script execution; `recommend('<math><mi>x</mi></math>')
  → "review"`, `recommend('<h1>safe</h1>') → "upgrade"`.
- **SAST re-executed** (uvx semgrep, custom + p/security-audit +
  p/owasp-top-ten + p/secrets) over the five changed frontend files → **0
  findings**; the reviewed-sink `nosemgrep` annotation holds.
- **Vulture gate re-executed CI-exact** (`scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'`) →
  **rc=0, 1414 → 1414**. Neither prior #817 debt identity
  (`VISUAL_ARTIFACT_BLOCK_REASONS`, `container.py`) appears. Note: running
  the script with NO args (whole tree incl. `tests/` and hive backend)
  exits 1 with mass pre-existing debt — proven develop-inherited, not this
  branch: every reported file is byte-identical to base (not in
  `git diff b906cc577..HEAD --name-only`) and the base ledger contains zero
  identities for them (e.g. `hive-conductor/backend/main.py`: 0 entries).
- **mypy AGENTS.md battery re-executed → Success: no issues in 715 source
  files.**
- **Closure-keyword review re-executed:** PR #1389 body says "Refs #817"
  only; `git log develop..HEAD` contains no fixes/closes/resolves for #817
  (one pre-existing "Closes #1422" in 6d8bd20a9 targets that commit's own
  task issue, not the review issue).

No production or test file changed this round (fresh validation evidence
only); no new tests added, so no inventory-delta change.

## Independent verification round 12 (auto-817 @ 15355a0702c2, verifier+writer lane)

Executed fresh at this job's exact starting head `15355a0702c2a0bd6b49d6aa5b9368f863ae6eb6`
(develop base `b906cc577fbb`), clean worktree before and after; resolves the prior
"verification worktree changed; evidence rejected" block. Round-11's driver checks
(job 11e37477) all passed at this head but the agent died on a provider timeout, so
every gate below was re-executed by this round, not carried over.

- **Lane gates re-executed:** driver set (check-0..7 logs, job
  8508e3700a524843bc7749dc355ba132) all rc=0; independently re-run: warden
  detector + vocabulary + design test_design/test_scan/test_trust_prescan →
  **217 passed**; `hive-conductor/backend/tests/test_design_renderers.py` →
  **7 passed**; `ruff check .` clean; `ruff format --check .` 2556 files;
  suite inventory → hive backend / maistro-core / maistro-design all match;
  mypy AGENTS.md battery + `packages/maistro-design/src` → **733 files, no
  issues**.
- **SAST gate re-executed CI-exact** (security.yml command: custom
  `tools/semgrep/maistro-rules.yaml` + p/security-audit + p/owasp-top-ten +
  p/secrets, eval/cage excluded) → **rc=0, 364 rules / 1895 files / 0
  findings**; the reviewed-sink `nosemgrep` annotation holds (round-2 finding
  closed).
- **Vulture gate re-executed CI-exact** (`scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'`) → **rc=0,
  1414 → 1414**; neither prior #817 debt identity appears (round-2 finding
  closed).
- **Pre-scan/output parity re-probed at this head** via
  `scan_and_record` + review-queue records vs `scan_design_text`: MathML,
  annotation-xml, event-handler attr, onbegin SVG, `javascript:` img,
  `data:text/html` iframe, CSS `url()`/`@import`/`expression()`,
  `<script>`, and prompt injection → all `skull / banish / conf 0.9` with
  explicit shared flags and `render_passed=False`; clean brief →
  `t3 / upgrade / conf 0.0 / passed`. `upgrade` iff the shared boundary
  passes on every probe (AC-2/AC-4). `<style>`-element and `<a>`-tag
  over-blocking is consistent on both sides (browser allowlist also drops
  them as `active-element`), i.e. conservative parity, not drift.
- **Browser corpus re-executed in real Chromium** (pre-built
  `auto817-playwright` image, live worktree sources copied to /live,
  image node_modules, `--network none`, output to /tmp; zero writes to the
  worktree): `deck-sanitization.spec.ts` → **8/8 passed (2.8s)**, including
  the MathML `active-element` scan-reason assertion,
  `recommend('<math><mi>x</mi></math>') → "review"`, the `\75rl(` and
  `\6a` escape families, srcdoc/meta-refresh/image-set payloads, and zero
  attacker-server requests / zero script executions.
- **Stop condition re-checked:** `maistro_design/scan.py` consumes
  `maistro.security.warden.patterns` only (no private vocabulary);
  `deckSanitizer.ts` is compatibility re-exports of
  `visualArtifactRenderer.tsx`; importer and `design_render.py` call the
  shared `scan_blocking_patterns`/`scan_design_text`.
- **Closure-keyword review re-executed:** `git log b906cc577..15355a070`
  bodies/subjects contain no `fixes/closes/resolves #N` for #817; PR #1389
  body says "Refs #817" only (draft). CI on the PR remains UNVERIFIED
  (snapshot carries no status claim).

No production or test file changed this round (fresh validation evidence
only); no new tests added, so no inventory-delta change.

## Independent repair-round verification 13 (auto-817 @ 2f787f977d26, verifier+writer lane)

Executed fresh at this round's exact starting head `2f787f977d26768d4a32e7c4db52c2f0dfe8f02a`
(develop base `31bddeb7b1ed`), clean worktree before and after. The job directory
for this round carried **no check-*.log files**, so no driver check was trusted:
every gate below was executed by this round at this head. Resolves the prior
"verification worktree changed; evidence rejected" block (head verified exact
via `git rev-parse` before validation started).

- **Lane gates:** `ruff check .` clean; `ruff format --check .` 2556 files;
  warden detector + visual vocabulary + design test_design/test_scan/
  test_trust_prescan → **217 passed**; `test_design_renderers.py` → **7
  passed**; suite inventory (maistro-core, maistro-design, hive-conductor
  backend) all match; AGENTS.md mypy battery + `packages/maistro-design/src`
  → **733 files, no issues**; CI-exact vulture
  (`scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`) → **rc=0, 1414 → 1414**.
- **SAST re-executed CI-exact** (security.yml command, semgrep 1.178.0 via
  uvx: custom maistro-rules.yaml + p/security-audit + p/owasp-top-ten +
  p/secrets, eval/cage excluded) → **rc=0, 364 rules / 1895 files / 0
  findings** (report kept outside the tree).
- **Pre-scan/output parity re-probed at this head** with an independent
  17-case corpus: script tag, event-handler attr, svg onload, script-in-SVG,
  svg `<use>` data URL, foreignObject, MathML, `data:text/html` iframe,
  `javascript:` img, meta refresh, CSS `url()`, escaped `\\75rl(`, `@import`,
  `expression()`, srcdoc, prompt injection → all `skull / banish / conf 0.9`
  with explicit shared flags AND `scan_design_text` blocked on every case;
  clean brief → `t3 / upgrade / conf 0.0 / passed` (AC-1/2/4; `upgrade` iff
  the shared boundary passes).
- **Render boundary probed:** `DesignRenderService._enforce_output_boundary`
  raises `TrustBannedError` on 8/8 hostile render inputs (script, handler,
  SVG script, data:text/html, CSS url()/`\\75rl`/@import/expression, meta
  refresh) and passes clean markdown (AC-3 server side).
- **Browser corpus re-executed in real Chromium with LIVE worktree sources**
  (`auto817-playwright:latest` image; live `frontend/src` + `tests/e2e`
  tar-copied to `/live` in-container, spec run from the image's `/tests` for
  node_modules resolution, `E2E_SRC_ROOT=/live`, `--network none`, output
  outside the worktree): `deck-sanitization.spec.ts` → **8/8 passed (3.5s)**,
  including the reason-name assertions (`active-element`,
  `css-network-or-code`), `recommend('<math><mi>x</mi></math>') → "review",
  and `__deckPwned=0` / zero attacker requests (AC-3 browser side, AC-5).
  **Harness pitfall recorded for future rounds:** bind-mounting the worktree's
  whole `frontend/` over the image's `/tests/frontend` drags in the worktree's
  `frontend/node_modules`, so esbuild resolves a *second* React copy for the
  frontend sources (entry uses image react, sources use worktree react) →
  "Invalid hook call / Cannot read properties of null (reading 'useState)'") →
  DeckBuilder never mounts → placeholder assertion times out. Copy sources
  without `node_modules` (as CI's Dockerfile COPY does) instead of bind
  mounting; the failure is environmental, not a code regression (reproduced
  with the image's own baked sources too).
- **Stop condition re-checked:** `maistro_design` consumes
  `maistro.security.warden.patterns` only (no private vocabulary);
  `visualArtifactRenderer.tsx` re-declares `VISUAL_ARTIFACT_BLOCK_REASONS`
  with the same four names and `test_visual_artifact_vocabulary.py` pins the
  Python table to the declared tuple by construction; `design_render.py` and
  the engine call the shared `scan_design_text`/`scan_blocking_patterns`.
- **PR/branch CI rollup remains UNVERIFIED** (snapshot carries no GitHub
  status claim; live GitHub not consulted per no-mutation scope). Prior
  CI-failure findings at this head (integration-scope, test,
  hive-conductor-e2e-ui, devskim, coverage gate) could not be reproduced
  locally for the parts with local equivalents: ruff/format/mypy/pytest/
  inventories/vulture/semgrep all green above.

No production or test file changed this round (fresh validation evidence
only); no new tests added, so no inventory-delta change.

## Independent verification 15 (auto-817 @ b37ae79e56fc, verifier+writer lane)

Executed fresh at this round's exact head `b37ae79e56fc4d9dca61948db376049013c36eca`
(clean worktree before and after; develop base `ca4caec7d319` confirmed as
ancestor via `git merge-base`, so the prior develop-sync block is resolved).
Driver checks from job `582e29468ba9` were re-run locally, not trusted:

- **Lane gates re-executed:** `ruff check .` clean; `ruff format --check .`
  2573 files; lane suite (log-redaction, detector, visual vocabulary,
  test_design/test_scan/test_trust_prescan) → **269 passed**;
  `test_design_renderers.py` → **7 passed**; suite inventories (hive-conductor
  backend 2815, maistro-core 11132, maistro-design 324) all match — the
  round-14 check-7 drift is resolved by the recorded +14 delta (b37ae79e5).
- **AGENTS.md mypy battery incl. `packages/maistro-design/src`** → **739
  files, no issues**. (Scoped per-package mypy that omits sibling `src`
  dirs reports `import-untyped` artifacts on `maistro.security.*` imports;
  the canonical all-sources invocation is the meaningful gate.)
- **CI-exact vulture** (`scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`) → **rc=0, 1412 → 1412**
  at this head (covers the baseline-script change from 13775de35).
- **Independent 10-case probe at this head** (own corpus, not the test
  suite): script, event-handler attr, script-in-SVG, `data:text/html`,
  CSS `url()`, escaped `\75rl(`, `@import`, `behavior: url(...)`,
  `-moz-binding: url(...)`, prompt injection → every case `skull / banish`
  pre-scan with explicit shared-vocabulary flags AND `scan_design_text`
  blocked; clean brief → `t3 / upgrade / passed` (AC-1/2/3/4).
- **Browser corpus re-executed in real Chromium** (playwright 1.60 /
  chromium-1223, CI-layout mirror built in /tmp: sources copied WITHOUT
  `frontend/node_modules`, single test node_modules, `E2E_SRC_ROOT` at the
  mirror): `deck-sanitization.spec.ts` → **8/8 passed (3.5s)**, including
  the exact shared reason-name assertions (`event-handler`,
  `css-network-or-code`, `active-element` — the cross-language vocabulary
  pin) and the poster/infographic/flyer shared-boundary journey (AC-3
  browser side, AC-5). Independently reproduced the round-13 double-React
  harness pitfall from the worktree layout (entry react vs shadowed
  frontend react → hooks crash → placeholder timeout); confirmed
  environmental, not a code regression.
- **Closure-keyword review:** PR #1389 body says "Refs #817" only; none of
  the 52 branch commits uses fixes/closes/resolves — no premature closure.
- **Stop condition re-checked:** `maistro_design` consumes
  `maistro.security.warden.patterns` only; `deckSanitizer.ts` is a
  deprecated shim over `visualArtifactRenderer.tsx` (single frontend
  boundary); `design_render.py`/engine call the shared
  `scan_design_text`/`scan_blocking_patterns`.
- **Remaining UNVERIFIED:** GitHub CI status rollup for PR #1389 (live
  GitHub not consulted per no-mutation scope); all local equivalents green.

No production or test file changed this round (fresh validation evidence
only); no new tests added, so no inventory-delta change.

## Independent verification 16 (auto-817 @ 2956f618e0ea470be95c396e8121db8ec9ab73ab, verifier+writer lane)

Fresh validation at the lane's exact head `2956f618e` (the round-15 note
pre-dates the `2956f618e` CI-repair commit, so no prior round section records
evidence AT this head; the repair lane's own result.json does, and this round
re-derives it independently). Read-only probes; the only tracked change in
this round is this note.

- **Driver deterministic checks confirmed**: `uv sync` env resolved; ruff
  check clean; ruff format clean (2573 files); lane battery 281 passed;
  renderer 7 passed; suite inventories ok (hive-conductor backend 2815,
  maistro-core 11137, maistro-design 331).
- **Lane suites re-executed by this round**: `packages/maistro-design/tests`
  → 331 passed; `packages/maistro-core/tests/security` → 1330 passed /
  19 skipped; `test_design_renderers.py` → 7 passed (pdf+pptx+docx all raise
  `TrustBannedError` before backend dispatch); the four #817 test files →
  154 passed.
- **Independent probe at this head (own corpus, not the suite)**: the issue's
  exact scenario `<script>...</script>` → `skull / banish / 0.9` with explicit
  shared flags (`script pattern: <script> tag`, `visual artifact
  active-element`) — no `upgrade` (AC-1/AC-2). Output boundary blocked all
  seven probes: `@import "https://..."`, `@import url(...)`, `data:text/html`
  link, `onerror` handler, CSS `url(//...)`, script-in-SVG, escaped `\75rl(`
  — the repaired `@import` arm is reachable end-to-end (AC-3). Pre-scan
  blocking flags ≡ output-boundary flags on every probe; clean brief stays
  `t3 / upgrade / ()` (AC-4, no over-blocking).
- **Browser corpus re-executed in real Chromium** (image rebuilt from this
  worktree's live sources via `tests/Dockerfile.playwright`, context
  = this head): `deck-sanitization.spec.ts` → **8/8 passed (3.6s)**,
  including the payload families, CSS obfuscation, the
  `recommendVisualArtifactTrust` parity block (blocked → `review`, never
  `upgrade`), and zero attacker-server requests (AC-3 browser side, AC-5).
- **Gates re-executed**: `ruff check .` clean; `check-suite-inventory.py`
  ok (13/13, incl. `tests/: 3754`, `formal/: 664`);
  `check-merge-markers.py` ok; vulture CI-exact argv
  (`packages/*/src --min-confidence 60 --exclude '*/third_party/*'`)
  → rc=0, 1412 → 1412 vs base `ca4caec7d3`.
- **Closure-keyword review re-executed:** supplied PR #1389 body says
  "Refs #817" only (draft: false, claim-stake wording); none of the branch
  commits `ca4caec..2956f618e` uses fixes/closes/resolves — no premature
  closure. Develop-sync block: worktree clean at `2956f618e`, no
  merge in progress, `ca4caec` already an ancestor via `775d54ac2`/`3925106f2`
  — nothing to redo.
- **Stop condition re-checked:** `maistro_design/scan.py` imports its
  vocabulary from `maistro.security.warden.patterns` (one Python authority);
  `deckSanitizer.ts` remains a deprecated shim; `design_render.py` and the
  engine call the shared `scan_design_text`/`scan_blocking_patterns`.
- **Remaining UNVERIFIED:** hosted GitHub CI rollup for PR #1389 at
  `2956f618e` (push forbidden); the DB-backed
  `check-ac-state.py --run-tests --ratchet --mandate ca4caec` battery was not
  re-run this round (repair-lane CI-exact reproduction at this same head
  recorded exit 0 / design coverage 38.0924; this round's targeted suites and
  inventories are green).

No production or test file changed this round (fresh validation evidence
only); no new tests added, so no inventory-delta change.

## Independent verification 17 (auto-817 @ d5febf7e569b, repair round: develop sync + gates)

This round's assignment was the preserved develop-sync block plus gate
re-validation. Executed at the fresh merge head `d5febf7e5` (merge of
`origin/develop` `c791724a8051` into `6ca41ab19`; conflict-free — the
round-14 union repair had already absorbed every overlapping hunk, so the
merge fast-content was clean and committed as-is). The develop base
`c791724a8051` is now an ancestor of the branch head; the develop-sync block
is resolved. No production or test file changed this round; the only tracked
changes are this note (and the merge itself).

- **Develop sync:** `git merge origin/develop` at clean tree → no conflicts,
  committed `d5febf7e5`. Diff `6ca41ab19..d5febf7e5` touches only develop's
  own files (agents seam fail-closed #1593, a11y keyboard #1590, their tests
  and notes) — zero overlap with #817 surfaces.
- **Lane gates re-executed at d5febf7e5:** `ruff check .` clean; `ruff
  format --check .` 2577 files; `packages/maistro-design/tests` → 331
  passed; `packages/maistro-core/tests/security/warden` → 111 passed
  (includes `test_visual_artifact_vocabulary.py` TS/Python lockstep);
  `packages/maistro-core/tests/security` → 1331 passed / 19 skipped;
  `packages/maistro-core/tests/agents` (merge-touched) → 793 passed;
  `test_design_renderers.py` → 7 passed. AGENTS.md mypy battery incl.
  `packages/maistro-design/src` → 739 files, no issues.
- **Independent 13-case probe** (own corpus, not the suite): script tag,
  event-handler attr, script-in-SVG, `data:text/html`, CSS `url()`, escaped
  `\75rl(`, `@import`, `behavior: url(...)`, `-moz-binding: url(...)`,
  prompt injection, iframe, `javascript:` URL → every case pre-scan
  `skull / banish` with explicit shared-vocabulary flags AND
  `scan_design_text` blocking flags (AC-1/2/3); clean brief stays
  `t3 / upgrade / ()` (AC-4, no over-blocking).
- **Browser corpus in real Chromium**: `deck-sanitization.spec.ts` →
  **8/8 passed (3.7s)** via the local `tests/e2e` harness with
  `E2E_SRC_ROOT=<worktree>/packages/hive-conductor` and
  `E2E_NODE_PATHS=<worktree>/packages/hive-conductor/frontend/node_modules`.
  Harness note: pointing `E2E_NODE_PATHS` at `tests/e2e/node_modules` (its
  own react copy) reproduces the duplicate-React "Invalid hook call /
  reading 'useState'" mount failure round 12 documented as environmental —
  the entry resolves bare `react` from `nodePaths` while `frontend/src/**`
  resolves from `frontend/node_modules`; the frontend path is the one that
  yields a single React. Payload families, CSS obfuscation,
  `recommendVisualArtifactTrust` parity (blocked → `review`, never
  `upgrade`), and zero attacker-server requests all green (AC-5).
- **Vulture CI-exact argv** (`scripts/check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'`) →
  **rc=0, 1411 → 1411** vs base `c791724a8051` (develop's own 1412→1411
  identity change rides along in the base; no branch-specific drift, no
  ledger amendment needed).
- **Prior `devskim = failure` finding dispositioned stale** (read-only `gh`
  queries, no mutations): at the exact prior head `6ca41ab19` the hosted
  workflows report **10/10 success including DevSkim** (run set
  2026-09-26T13:35:58Z); the only non-success runs on the branch are two
  *cancelled* `quality`/`CI` runs at superseded merge head `834019512`.
  Run id `108414464052` returns 404 (expired/pruned). No devskim toolchain
  exists locally (no dotnet), so hosted evidence is the authoritative one
  and it is green.
- **Other gates:** `check-merge-markers.py` ok post-merge; CI-exact
  `check-suite-inventory.py` (no args) → 13/13 suites match (an accidental
  `--compact` fold of `baseline.json` made mid-round was reverted by
  rewriting the file from `HEAD` content before any commit; the no-arg check
  confirms the restored state).

No production or test file changed this round (merge + fresh validation
evidence only); no new tests added, so no inventory-delta change.
