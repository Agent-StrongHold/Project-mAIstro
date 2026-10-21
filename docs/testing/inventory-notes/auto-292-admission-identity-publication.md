---
inventory-delta:
  packages/maistro-core/tests: +3
---

# auto-292 — admission identity publication (#1859 carry-over)

Carries the #1859 tree-side fix that greens the inherited exact-debt-ledger red:
`maistro.runs` now publishes the admission identity vocabulary
(`AdmissionBinding`, `AdmissionRecordV2`, `CanonicalJsonObject`,
`LegacyAdmissionRecord`, `RootAdmissionEnvelope`) so the contract leaf
`maistro.runs.admission_identity` is reachable from the package surface.
Three node IDs are added in
`packages/maistro-core/tests/runs/test_runs_admission_identity_publication.py`
pinning the publication and the single production edge.
