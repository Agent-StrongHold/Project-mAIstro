---
inventory-delta:
  tests/: +39
---

# The setup-uv release is the flake fix, not the uv pin (#213)

Thirty-nine root-suite node IDs in `tests/test_check_uv_setup.py` — twenty-nine
with the implementation, ten more from review. No other suite moves: the change
is workflows, one composite action, one script and its tests.

Nine of the thirty-nine are parametrized cases rather than nine `def`s, which is
the understatement the node-ID count exists to avoid: six non-exact uv version
forms and three exact ones, each asserted separately because each is a distinct
way to be wrong.

The split matters more than usual here, because this change pins **two** things
for **two different reasons**, and conflating them is the exact mistake #213
made — and that the first version of this PR then repeated.

- **4** guard the pinned **action release** (`TestActionReleaseIsPinned`). This
  is the actual fix. `setup-uv` fetches the version manifest unconditionally —
  measured three ways on this PR — so the fetch cannot be avoided and only its
  *tolerance* can be chosen. Dropping back to `v7`, or to a floating major that
  does not resolve, must fail.
- **13** guard the **exact uv version** (`TestVersionMustBeExact`). Real, but a
  determinism defect rather than the flake: `quality.yml` ran uv 0.5.31 while
  every other job ran 0.12.5. The tests say so in their own docstrings, so a
  later reader cannot pick up the false version of the story.
- **5** guard that no workflow calls `astral-sh/setup-uv` directly, in each form
  it can appear — with a ref, without one, and the `- name:` then `uses:` form.
  That last is not hypothetical: it is the shape that hid three stale
  `version: "0.5.x"` inputs from the first pass of this change's own rewrite,
  because its `with:` sits at the same indent as its `uses:` rather than deeper.
- **4** drive `main`, including that one run reports every problem rather than
  the first.
- **3** run the gate against this repository as committed, so the twenty routed
  usages and both pins are facts about the tree, not only about fixtures.
- **10** are regressions for review findings, below.

## Ten from review

Codex raised three findings on the gate, and all three were the same shape as
the bug the gate exists to prevent — a check that reports success while
checking nothing. Two of them were defeated by *quoting* or by *renaming a file
extension*, which is not a high bar.

- `.yaml` workflows were not scanned at all. GitHub runs them.
- The line regex missed `uses: astral-sh/setup-uv@v7 # install uv` and the
  quoted form `uses: "astral-sh/setup-uv@v7"`. Both run the action.
- The wrapper check was a substring search over the file text, and this file's
  comment block names the action and its version repeatedly — so the prose
  explaining the pin satisfied the check that the pin existed. Swapping the
  real step for a different action, comments intact, passed.

All three are gone because the gate now **parses the YAML** instead of matching
text: workflow `uses:` values come from the parsed document (walked whole, so a
job-level `uses:` for a reusable workflow is caught too), and the wrapper is
read from its own `runs.steps`. Three of the ten regressions cover spellings,
one covers job-level `uses:`, two cover comments-are-not-configuration, and the
rest cover malformed input — including one that pins the *deliberate* decision
to skip a workflow that does not parse, since `actionlint` runs in the same job
and fails on it first.

## What this cost, and what it bought

Three CI measurement commits, none of them fixes, deliberately pushed to learn
what could not be learned locally:

| commit | wrapper | measured |
|---|---|---|
| `e26009a` | `@v7` + `0.12.5` | fetches the manifest anyway |
| `d5257cf` | `@v7` + `latest-known` | fetches, then `No version found` |
| `6639249` | `@v10` | `Unable to resolve action` — no such ref |
| `051ed86` | `@v10.0.1` + `0.12.5` | fetches, installs, green |

The first of those overturned this change's original premise, which had been
taken from a summarised reading of the action's source instead of from a run.
The record now states the weaker, true claim: the fetch is unavoidable, and
what the upgrade buys is tolerance of its failure — which is the release's
stated purpose and is *not* verified here, because simulating a CDN outage in
CI was not available.
