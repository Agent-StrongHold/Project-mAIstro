---
tests-run:
  - "uv run pytest packages/maistro-design/tests -x -q -> 297 passed"
    - "uv run pytest packages/maistro-core/tests/runs packages/maistro-server/tests/api -q -> 1252 passed, 209 skipped"
    - "uv run pytest packages/maistro-rsi/tests -q -> 779 passed"
    - "npx playwright test visual-artifact-boundary.spec.ts -> 3 passed"
    - "npx playwright test deck-sanitization.spec.ts -> 8 passed"
    - "npx playwright test design-studio-keyboard.spec.ts -> 4 passed"
    - "npx playwright test design-studio-truthfulness.spec.ts -> 5 passed"
    - "uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude '*/third_party/*' -> exit 0, unclassified: 0"
    - "uv run ruff check . -> all checks passed; uv run ruff format --check . -> 2572 files formatted"
    - "uv run python scripts/check-frontend-api-routes.py / check-doc-links.py / check-cross-package-imports.py -> all OK"
---

# auto-768 develop-sync merge resolution (round 3, #768)

## What was conflicted

Merging origin/develop (ca4caec7d, head commit dd16ef2cf "Make Design Studio
and its artifact editors keyboard-complete (#1460)") into auto-768 produced
exactly two content conflicts:

- `packages/hive-conductor/frontend/src/pages/DeckBuilder.tsx`
- `packages/hive-conductor/frontend/src/pages/DesignStudio.tsx`

Everything else merged cleanly, including develop's `FixedPageEditor.tsx`
(structured layer editor), its e2e additions, and the RSI/warden/harvest
changes.

No collected count moved in this merge resolution (the `inventory-delta:`
key is therefore absent — the ledger's normal case for a change that moved no
node IDs). The files whose resolution is recorded here:

- `packages/hive-conductor/frontend/src/pages/DesignStudio.tsx` — merge
  resolution: hybrid of keyboard-complete shell + #768 shared visual-artifact
  boundary persistence/inline editor
- `packages/hive-conductor/frontend/src/pages/DeckBuilder.tsx` — merge
  resolution: keyboard-complete Deck structure; all three executable sinks
  rerouted through the shared visualArtifactRenderer boundary
- `packages/hive-conductor/frontend/src/lib/deckSanitizer.ts` — compat
  wrapper now also exports `writeSanitizedVisualArtifact`
- `packages/hive-conductor/frontend/src/pages/FixedPageArtifactEditor.tsx` —
  contenteditable preview gets `role=textbox`/`aria-multiline` for accessible
  naming

## Resolution decisions

### DeckBuilder.tsx — develop's keyboard-complete structure, #768 sink discipline

The merged e2e contract (design-studio-keyboard.spec.ts) requires develop's
keyboard-complete Deck editor (props, "Deck title" entry focus, Present dialog
with aria-modal trap, ordered-page listbox). develop's version, however, held
three raw executable sinks (`dangerouslySetInnerHTML` x2, `template.innerHTML
=`, `currentTarget.innerHTML =`) that the #768 static contract
(visual-artifact-boundary.spec.ts) forbids outside the shared renderer.

Resolution: develop's structure with every sink rerouted through the shared
boundary — `SanitizedVisualArtifact` for preview + presentation markup,
`createSanitizedVisualArtifactFragment` for paste/drop insertion,
`writeSanitizedVisualArtifact` for the blur-time DOM write. This preserves the
#752 hostile-corpus proof (deck-sanitization.spec.ts passed 8/8 against the
merged component, including `attackerRequests == []` and `__deckPwned == 0`).

### DesignStudio.tsx — hybrid: keyboard shell + boundary-backed inline artifact editor

The merged truthfulness spec requires BOTH:

- develop's brief/catalog/projects shell with the structured
  `FixedPageEditor` behind "Open editor" ("Infographic editor", "Draft editor
  ready", no fake canvas execution), and
- the #768 rehydration journey ("fixed-page artifacts rehydrate through the
  shared boundary"): an inline, always-mounted `FixedPageArtifactEditor` for
  the selected fixed-page mode that sanitizes persisted markup on read,
  keeps the pre-scan verdict in localStorage next to the sanitized markup,
  and rewrites legacy raw-string payloads on mount.

So the resolved page mounts develop's shell verbatim, plus the boundary-backed
inline editor section (hidden for deck mode, unmounted while a structured
editor is open). The availability list keeps develop's post-#769 truthful copy
(deck no longer claimed "closed").

### deckSanitizer.ts / FixedPageArtifactEditor.tsx

- Compat wrapper now also re-exports `writeSanitizedVisualArtifact` so Deck
  has no reason to touch the DOM directly.
- The fixed-page contenteditable preview gets `role="textbox"`
  `aria-multiline="true"` (same pattern as the merged Deck slide editor) so
  axe's naming rules are satisfied; the axe scans in
  design-studio-keyboard.spec.ts pass with the inline editor mounted.

## Evidence

All commands in `tests-run` above executed in this worktree against the
resolved tree; the four Playwright specs ran against the freshly built
`hive-conductor-hive` image (commit content of this branch), published on
localhost:48101 for the two app-level specs. The prior finding "scan.py
misses renderer's CSS-comment rejection; probe returned tier=t3
recommendation=upgrade" was re-probed directly:
`scan_and_record('<div style="background: url(http://attacker.invalid/x)/*..*/;color:red">css</div>')`
now returns `tier=skull recommendation=banish
flags=('css-network-or-code',)`.

Residual: the PR's GitHub CI (devskim etc.) remains IN_PROGRESS per the prior
round; no GitHub mutations are performed from this lane.

## Repair round (2026-08-31 audit follow-up)

The prior verify round failed `uv run python scripts/check-suite-inventory.py
--suite packages/maistro-design/tests` with exit 2: this note's front matter
used an `added: []` / `removed: []` / `changed:` schema the ledger cannot
parse (`cannot read 'added: []' as '<suite>: <±count>'`). The merge resolution
moved no collected node IDs, so the correct form is no `inventory-delta:` key
at all — the ledger's documented normal case — with the file list kept in the
body above.

Re-validation at head baf36a384 (all executed in this worktree):

- `uv run python scripts/check-suite-inventory.py` (full, as ci.yml runs it)
  -> `ok: 13 suite(s) match the recorded inventory` (design 297, e2e 23).
- `uv run pytest packages/maistro-design/tests -q` -> 297 passed.
- `uv run ruff check .` / `uv run ruff format --check .` -> pass (2574 files).
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` -> exit 0, unclassified 0.
- Playwright in the CI-equivalent Docker image built from this tree
  (`tests/Dockerfile.playwright`): visual-artifact-boundary (3) +
  deck-sanitization (8) -> 11 passed; against the app image
  (`packages/hive-conductor/Dockerfile`) published on localhost:48101:
  design-studio-truthfulness (5) + design-studio-keyboard (4) -> 9 passed.
- `scan_and_record` probes (job #817 parity): CSS
  `background:url(...)`+comment -> skull/banish `css-network-or-code`;
  script+foreignObject+`data:text/html`+onload SVG -> skull/banish; safe
  poster markup -> t3/upgrade with empty flags.

Note on local runs: `deck-sanitization.spec.ts` cannot run outside the Docker
image on a dev checkout because `frontend/node_modules` (react 19.2.6) and
`tests/e2e/node_modules` (react 19.2.0) would give the esbuild harness two
React copies ("Invalid hook call"); the image copies only one. The Docker run
is the CI shape and is the evidence that counts.
