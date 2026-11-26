---
inventory-delta:
  packages/maistro-core/tests: +3
---

# auto-944-ee1c

Develop-sync merge resolution round. The +3 node IDs come from the merge of
origin/develop (e20e9f52) which brought in the admission-identity surface
(`packages/maistro-core/src/maistro/runs/admission_identity.py` and its test),
adding 3 collected tests to `packages/maistro-core/tests`. No #944 extension
test files were added or removed in this round; the extension policy/quarantine
suites remain at their prior counts.
