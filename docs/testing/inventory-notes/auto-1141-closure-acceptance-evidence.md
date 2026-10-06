---
inventory-delta:
  tests/: +20
---
# auto-1141-closure-acceptance-evidence

Extends `tests/test_check_closure_targets.py` for the #1141 acceptance-evidence
gating of `scripts/check-closure-targets.py`: 58 node IDs on this branch vs 38
at the base (df00785), all additions — nothing removed or moved. New coverage:
the acceptance-record parser (checkbox items under acceptance headings; prose
bullets register nothing), claimed-criterion parsing (closing lines only, so
`Part of #76 AC-2` stays progress language), open-children refusals replacing
the any-children refusal, and the issue fixtures that reproduce the confirmed
false closes — #56/#62/#465 (untagged parents with open direct children) and
#76 (leaf closed completed while all nine registered criteria were unticked;
a locally green diff is not an input to the verdict). Also pins the
already-closed-target skip, the fail-safe default of a missing issue state to
`open`, and sub-issue pagination for the open-children lookup. The GitHub
lookup is monkeypatched, so the suite stays offline.
