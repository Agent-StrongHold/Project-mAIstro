---
inventory-delta:
  tests/: +23
---

# 564-branch-protection-drift-guard

## What moved

Twenty-three tests in `tests/test_check_branch_protection.py`, covering the two
new surfaces of `scripts/check-branch-protection.py` added for #564:

- `TestRulesetSurfaceReading` (7) — parsing the Rulesets API shapes the
  2026-11-26 read-back produced: `ref_name` include/exclude/`~DEFAULT_BRANCH`
  matching, exclusion outranking inclusion, disabled rulesets governing
  nothing, `{integration_id, context}` extraction, strict-freshness extraction,
  missing-rule tolerance, and `declared_required` folding the Ruleset-only
  `additional_required_checks` (`gates-ran`) into the effective declared set.
- `TestVerifyRulesets` (8) — the new `--verify-rulesets` drift detector: a
  matching live ruleset passes; context drift is named in both directions; a
  declared branch with no governing ruleset fails; strict-freshness divergence
  is named; merge-queue posture divergence is named against the real
  `.github/merge-queue.json` (HEADGREEN vs ALLGREEN included); a declared
  queue with no live `merge_queue` rule fails; the CLI wires the mode, and a
  missing token SKIPs like `--verify`.
- `TestApplyFreezeGuard` (10) — the guarded `--apply` (#564 AC-3): tokenless
  apply refuses unconditionally without leaking the payload; an unknown branch
  still refuses; a newly required context that an open PR currently fails is
  refused and names the PR; a never-reported newly required context is refused
  (`Expected` forever); a context that is *already* required live and red does
  not block (the guard keys on newly required, not on any red check); a
  pending head counts as frozen; `--allow-freeze` prints the payload and
  re-states who it freezes; a clean apply prints the payload; and a re-run's
  success outranks an earlier failure of the same check name.

One existing test changed shape, adding no node:
`test_the_apply_payload_carries_no_comment_keys` now runs through the guarded
`--apply` path (token set, live ruleset mirroring the shipped file) because
`--apply` without a token refuses by design since this change.

## Why they exist

Issue #564: the declared ruleset and the live rulesets had drifted, and the
drift was invisible — the classic protection endpoint needs admin scope and
carries no required contexts at all since #162. `--verify-rulesets` makes the
delta measurable with an ordinary token (so CI can schedule it), and the
guarded `--apply` stops an apply from freezing open PRs silently. The tests
pin the failure diagnoses (which PR, which context, which direction), not just
exit codes, and drive the API through a URL-routing `_get` fake so they stay
offline and deterministic.

## Verification

`uv run pytest tests/test_check_branch_protection.py -q` → 63 passed.
`GH_TOKEN=… python3 scripts/check-branch-protection.py --verify-rulesets`
against the live repo → exit 1 with the measured drift named per context and
per queue parameter (recorded in docs/ci/BRANCH-PROTECTION.md, 2026-11-26).
`GH_TOKEN=… … --apply develop` → exit 1, 83 (PR, context) freeze pairs named,
no payload printed.
