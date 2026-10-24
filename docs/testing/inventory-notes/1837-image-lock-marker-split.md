---
inventory-delta:
  tests/: +5
---
# #1837 lane CI repair: image-lock reconcile accepts marker-split versions

fastmcp 4.1.3 resolves beartype per `python_full_version`, so `uv export
--locked --package maistro-server --extra image` legitimately emits two pins
for one name (`beartype==0.22.9 ; < '3.15'`, `beartype==0.23.1 ; >= '3.15'`).
`scripts/check-image-lock-reconciliation.py` collapsed the export to one pin
per name (last line wins) and failed the hosted python:3.13 engine image that
correctly installed 0.22.9 with `version mismatch: beartype==0.22.9 (image)
!= beartype==0.23.1` (security.yml "Reconcile installed packages to uv.lock",
run 40096048976/job 120878426851). The fix keeps every emitted pin per name
and accepts any of them at reconcile; a version outside the emitted set still
fails, naming every acceptable branch.

Five cases added to `tests/test_check_image_lock_reconciliation.py`: split
parsing keeps both pins; a parametrized pair proves either installed branch
reconciles; an absent split name still gates nothing (all-conditional);
a version outside the split fails once, naming every branch. All five fail
against the pre-fix script (parse collapses to `beartype==0.23.1`), pass
after. The engine/research/rsi exports each carry the split; hive-conductor's
carries none, so its reconcile is unchanged.
