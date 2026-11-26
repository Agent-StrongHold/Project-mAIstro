# #817 CI repair — DevSkim GHAS check failure (3 false positives on security code)

Repair round for the finding recorded at head `115e406f5`: the GitHub Advanced
Security `devskim` check-run failed with "3 new alerts in code changed by this
pull request" (run 108463775098), while the Actions DevSkim workflow itself
succeeded. No test counts moved in this round, so this note carries no
`inventory-delta` block.

## The three alerts

| Location | Rule | Text DevSkim matched |
| --- | --- | --- |
| `packages/hive-conductor/frontend/src/lib/visualArtifactRenderer.tsx:298` | DS137138 (Insecure URL) | `http://www.w3.org/2000/svg` |
| `packages/hive-conductor/frontend/src/lib/visualArtifactRenderer.tsx:315` | DS137138 (Insecure URL) | `http://www.w3.org/2000/svg` |
| `packages/maistro-core/src/maistro/security/warden/patterns.py:231` | DS189424 (Review eval) | the `eval()` in the detection label `"script pattern: eval()"` |

All three are false positives on the #768 security boundary itself:

- The SVG string is the W3C-fixed XML namespace identifier that `DOMParser`
  stamps on parsed SVG elements. It is a namespaced name, not a network
  address — nothing ever fetches it, and TLS is meaningless for it. DevSkim's
  rule (`http://[^/^\s^"]+`, scope `code`) pattern-matches the scheme prefix
  and cannot tell the difference.
- The Warden line is the *scanner that blocks* eval-like constructs; the rule
  fired on the entry's human-facing label, not on any executed call.

## What was verified before fixing (DevSkim 1.0.90, the action's engine)

`microsoft/DevSkim-Action@v1` runs a Dockerfile that installs
`Microsoft.CST.DevSkim.CLI` from NuGet unpinned — i.e. the current release,
1.0.90. The same package was installed locally (dotnet tool) and driven
against the pre-change files; it reproduced all three findings at the exact
lines and columns GHAS annotated, which makes the local harness authoritative
for the fix.

Bisecting suppression syntax against that engine produced facts that
contradict the older compact documentation and are worth recording for the
next person:

1. `// devskim:ignore DSxxxx` (no space after the colon) **does not work** in
   1.0.90 — the magic phrase requires whitespace: `devskim: ignore` /
   `DevSkim: ignore` (case-insensitive).
2. A standalone suppression comment on the line **above** the finding does
   not suppress it; only a same-line suffix comment does.
3. The `until YYYY-MM-DD` expiry is optional but kept — a dated suppression
   forces re-review.

A second trap surfaced for the Python entry: DS189424's pattern is
`\beval\(([^,]+)\)`. While the label and the tuple's closing bracket shared
one line, the pattern matched *across* `eval()"),` — string content, closing
quote, and bracket — even though the parens around `eval()` are empty. The
ruff-format-pinned exploded tuple breaks that accidental cross-token match,
and the label line additionally carries a same-line suppression for the same
rule so a future re-flow cannot reintroduce the annotation silently.

## The fix

- `visualArtifactRenderer.tsx`: both inline namespace literals were replaced
  by one `SVG_NAMESPACE_URI` constant carrying a single same-line
  `// DevSkim: ignore DS137138 until 2027-12-31` suppression with a comment
  explaining why the rule is a false positive for this literal. Renderer
  behavior is unchanged (same comparisons, same reasons).
- `patterns.py`: the SCRIPT_PATTERNS eval entry stays in its exploded form
  with the label on its own line plus a same-line
  `# DevSkim: ignore DS189424 until 2027-12-31` suppression and a comment
  documenting the cross-token match. Vocabulary, descriptions, and detection
  behavior are unchanged.

## Validation

- `devskim analyze` (1.0.90, full default rule set) on both post-change files:
  **zero findings** (pre-change: the three alerts above).
- `uv run ruff check .` / `uv run ruff format --check .`: pass (2585 files).
- Frontend `npm run lint` (0 errors, 95 warnings — the pre-existing baseline
  under the 96 ceiling) and `npm run build` (both `tsc --noEmit` passes +
  vite): pass.
- `uv run pytest packages/maistro-core/tests/security/warden/...` +
  `packages/maistro-design/tests` (437 passed) and
  `packages/hive-conductor/backend/tests/test_design_renderers.py`
  (7 passed).
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'`: ratchet green, 1406 → 1406, no ledger change
  (this round eliminates no identities).
- `scripts/check-suite-inventory.py --suite ...` for maistro-core,
  maistro-design, and hive-conductor backend tests: ok.

The GHAS check-run itself can only be re-evaluated after the fix is pushed;
the local reproduction is the evidence available inside the worktree.
