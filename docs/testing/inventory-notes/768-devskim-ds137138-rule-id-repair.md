# Issue #768 — DevSkim repair: the suppression named the wrong rule ID

Repair round for the prior verification finding *"gh pr view: devskim
failure"*. No test counts moved, so there is no `inventory-delta` block.

## The finding (read from CI, not guessed)

The `devskim` check run at pushed head `0d68a75e3272` (check-run id
108336908736) failed with exactly one annotation, warning level:

- `packages/hive-conductor/frontend/src/lib/visualArtifactRenderer.tsx:232`
  — "An HTTP-based URL without TLS was detected." ("Insecure URL"),
  summary "1 new alert" — the only alert attributable to this PR's changed
  code (all other open DevSkim alerts — `DS162092` on workflow files,
  `DS172411` on `api.ts:44`, … — pre-exist on develop and appear in every
  PR's whole-repo analysis, ~620 results).

Line 232 is the `SVG_NAMESPACE` constant that already carried the inline
suppression installed by the earlier round
(`768-devskim-svg-namespace-suppression.md`):

```ts
const SVG_NAMESPACE = "http://www.w3.org/2000/svg"; // devskim: ignore DS137837
```

## Root cause (empirically reproduced, not guessed)

DevSkim CLI 1.0.90 (latest published .NET tool — the distribution channel
`microsoft/DevSkim-Action@v1` installs from) run in a
`mcr.microsoft.com/dotnet/sdk:9.0` container over the file reports the
finding as **DS137138**, not DS137837:

```
visualArtifactRenderer.tsx:232:23:232:40 [Moderate] DS137138 Insecure URL
```

and the SARIF result carries `"suppressions": none`. The suppression
grammar and placement were fine; it named the wrong rule ID, so it never
applied. (DS137837 and DS137138 are both insecure-URL rules in the pack;
this rulepack version fires the former numbering on this literal. The
previous note derived DS137837 from the annotation text, which carries the
shared description, not the effective rule ID.)

## The repair

The suppression now names both insecure-URL rule IDs so a rulepack
renumbering cannot resurrect the false positive:

```ts
const SVG_NAMESPACE = "http://www.w3.org/2000/svg"; // devskim: ignore DS137138,DS137837
```

The comment block above the constant was corrected to record DS137138 as
the verified ID. Behavior is unchanged — same string, same `===`
comparison, comment-only edit.

## Evidence executed at the repaired tree

- DevSkim CLI 1.0.90 in the sdk container, on the repaired file's copy:
  with `// devskim: ignore DS137837` → 1 result (line 232, unsuppressed);
  with `// devskim: ignore DS137138` → **0 results**; with the committed
  comma form `DS137138,DS137837` → **0 results**.
- Same container run over the whole PR-changed shipped surface
  (`frontend/src`, mirroring the workflow's ignore-globs intent): exactly
  three findings, all accounted for — `api.ts:44` DS172411 and
  `MCP.tsx:136` DS162092 are pre-existing trunk alerts on files this PR
  does not touch, and `visualArtifactRenderer.tsx:232` is the one this
  repair suppresses. No other new-alert candidate exists in the diff.
- Frontend `tsc -p tsconfig.json --noEmit` and
  `tsc -p tsconfig.node.json --noEmit` — clean;
  `eslint src/lib/visualArtifactRenderer.tsx` — 0 errors.

## Residual risk

The action's pinned DevSkim version may differ from 1.0.90; the comma-form
suppression covers both known insecure-URL IDs, and the annotation set at
any future failing head remains a one-line diagnosis. DevSkim is advisory
per `.github/branch-protection.json` (documented non-required check), so
it cannot block integration either way — this repair exists to keep the
PR's new-alert count at zero, not to unblock a required gate.
