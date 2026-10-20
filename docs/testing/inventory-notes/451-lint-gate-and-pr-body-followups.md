---
inventory-delta:
  packages/maistro-rsi/tests: +5
---
# 451-lint-gate-and-pr-body-followups

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

Five node IDs added under `packages/maistro-rsi/tests`, no other suite moved.
All five close review follow-ups on the #304/#820 gate-evidence contract from
issue #451 Wave 2:

- `test_gate_evidence.py` (+4): a required analyzer that exits with a
  usage/configuration error (not 0/1) is a blocking `not_run` gate, never a
  clean parse of empty stdout (`d6d406e07`); in a mixed harvest group each
  unevidenced promotion is named individually as unverified instead of
  inheriting an evidenced sibling's vouch (`9f8cfc3df`); an UNAVAILABLE
  gate state outranks a passed record when group evidence merges, so a gate
  that never executed for one shipped patch cannot render as passed for the
  group (`9ba4d59c9`); and the gate provenance digest covers stdout AND
  stderr, length-framed, so a crashing-but-quiet analyzer no longer carries
  a clean run's digest (`32fe74725`).
- `test_selfbranch.py` (+1): the self-branch default PR body names the source
  pin the run actually resolved and verified (`run_self_branch_attempt`'s
  resolved digest), not `attempt.commit`, which is unset on the default
  `new_attempt()` path and rendered as the literal "unresolved".

The same change set refactors `_lint_gates` (complexity 13 → 3), the
`_scorecard_trace` gate-evidence bundle (12 → 6), and `_export_entry`
(11 → 4) into named helpers, pruning the now-stale
`candidate_fitness.py::_lint_gates` row from `quality/radon-baseline.json` —
behavior and messages unchanged, pinned by the existing gate-evidence cases.
