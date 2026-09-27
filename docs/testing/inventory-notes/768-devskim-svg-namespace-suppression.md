# Issue #768 — DevSkim DS137837 repair: SVG namespace constant

Repair round for the prior finding "CI at 7e3364012: devskim = failure".
No test counts moved, so there is no `inventory-delta` block.

## The finding (read from CI, not guessed)

The DevSkim check run at head `7e3364012` failed with exactly two annotations
(fetched read-only via the check-run annotations API):

- `packages/hive-conductor/frontend/src/lib/visualArtifactRenderer.tsx:301:42`
- `packages/hive-conductor/frontend/src/lib/visualArtifactRenderer.tsx:321:42`

both `DS137837 — An HTTP-based URL without TLS was detected (Insecure URL)`,
pointing at the string literal `"http://www.w3.org/2000/svg"`. That literal is
the W3C SVG namespace identifier fixed by the DOM specification; scrubbing
compares `namespaceURI` against it to pick the SVG vs HTML allowlist. It is an
opaque namespace constant, never fetched — a true scanner false positive, and
it cannot be "fixed" by changing the string without changing what the DOM
comparison means.

## The repair

`visualArtifactRenderer.tsx` now defines the identifier once:

```ts
const SVG_NAMESPACE = "http://www.w3.org/2000/svg"; // devskim: ignore DS137837
```

with both scrub sites (`attributeAllowed`, `scrubTree`) comparing against the
constant. Behavior is unchanged (same string, same `===` comparison); the two
annotated lines no longer contain a URL literal, and the single remaining
literal carries a narrowly scoped inline suppression on its own line.

Suppression grammar was verified against upstream DevSkim source
(`Microsoft.DevSkim/Suppression.cs`): the pattern
`DevSkim:\s+ignore\s+([a-zA-Z\d,:]+)` is matched with
`RegexOptions.IgnoreCase` against `GetLineContent(issue.StartLocation.Line)` —
the finding's own line — so a same-line trailing comment with the rule ID is
the supported form. This is deliberately *not* a workflow `exclude-rules`
entry: `devskim.yml` documents that suppressing the rule repo-wide would also
silence it on shipped code, and this keeps the suppression to one reviewed
line with its justification adjacent.

## Evidence executed at the repaired tree

- Full Playwright suite re-run against the repaired sources: the
  `tests/Dockerfile.playwright` image was rebuilt from this worktree (it COPYs
  `visualArtifactRenderer.tsx` and the consuming pages) and executed against
  the compose hive — **89 passed, exit 0**, including
  `visual-artifact-boundary.spec.ts` (exactly-one-sink whole-`src` scan + the
  Deck/DesignStudio/FixedPageArtifactEditor consumption contract) and
  `deck-sanitization.spec.ts` (hostile corpus + poster/infographic/flyer
  shared-boundary journeys with zero attacker requests).
- `visual-artifact-boundary.spec.ts` also run standalone locally: 3/3 passed.
- Frontend `npm run build` (`tsc -p tsconfig.json --noEmit`,
  `tsc -p tsconfig.node.json --noEmit`, `vite build`) — clean;
  `eslint src/lib/visualArtifactRenderer.tsx` — 0 errors; `npm run lint`
  overall — 0 errors, 96 warnings (the configured `--max-warnings 96` budget;
  the edit adds no exports so no new warnings).
- `uv run ruff check .` / `ruff format --check .` — pass;
  `uv run pytest packages/maistro-design/tests -q` — 294 passed;
  `scripts/check-suite-inventory.py --suite packages/maistro-design/tests` — ok;
  `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` — exit 0 (no ledger amendment needed).

## Residual risk

DevSkim itself only runs on GitHub (no dotnet toolchain locally), so the
suppression's effect is proven by reading the scanner's own source and
re-deriving the annotated findings, not by a local DevSkim run. If CI still
reports DS137837 after this change, the next candidate would be a version
drift in suppression parsing — the URL literal is confined to one line either
way, so diagnosis is a one-annotation check.
