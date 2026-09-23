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
