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
a version outside the split fails once, naming every branch. Four of the five
fail against the pre-fix script (parse collapses to `beartype==0.23.1`) and
pass after; the fifth
(`test_marker_split_pin_absent_from_image_still_gates_nothing`) is the
behavior-preservation guard — an all-conditional name gates nothing both
before and after, and it pins that the fix does not make an absent split name
start failing. The engine/research/rsi exports each carry the split;
hive-conductor's carries none, so its reconcile is unchanged.

Round-4 re-verification (2026-10-24, job 70562a49, head 4cb4b70a9): all four
CI reconcile sub-commands re-run gate-exact (security.yml lines 493-540
arguments) against images freshly rebuilt from this exact tree with the CI
apt-stage flag — `maistro-engine:pr-2268-r5` (python 3.13.16, in-image
`beartype==0.22.9`), `hive-conductor:pr-2268-r5`,
`maistro-engine-research:pr-2268-r5`, `maistro-rsi-runner:pr-2268-r5` — all
four print `OK: ... ships exactly the locked set` and the step exits 0. The
pre-fix script (extracted from parent fe7020f5a) run against the same engine
image and the same fresh export reproduces the hosted failure verbatim:
`version mismatch     : beartype==0.22.9 (image) != beartype==0.23.1`, exit 1.
In an isolated prefix against that pre-fix script, 4/5 new tests fail and all
32 pass at HEAD.
