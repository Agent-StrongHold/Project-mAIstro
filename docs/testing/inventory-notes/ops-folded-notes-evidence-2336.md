---
inventory-delta:
  tests/: +3
---

# ops/folded-notes-evidence (PR #2336)

Follow-up to #2334: folded_notes acceptance evidence class migration. Adds
`test_folded_notes_baseline_is_evidence_not_policy` (policy inputs),
`test_folded_notes_evidence_is_yellow_eligible` and
`test_blast_radius_yellow_stays_ineligible` (quality classes).
