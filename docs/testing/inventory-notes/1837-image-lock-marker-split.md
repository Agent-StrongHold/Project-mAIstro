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

Round-5 develop-sync resolution (2026-10-24, merge commit 72f116009): develop
(f956a8142, via 461fb86b1) independently landed the SAME marker-split fix
(merge-queue run 40085096483) and the sync left
`scripts/check-image-lock-reconciliation.py` conflicted between the two
equivalent implementations. Resolution adopts develop's script verbatim
(`_expected_clause`, `one of ...` mismatch wording; the script is now
byte-identical to trunk, minimizing the eventual merge-back diff) and re-pins
the branch-added
`test_version_outside_the_marker_split_fails_naming_every_branch` to develop's
message format. The auto-merged test file carries both sides' split tests
(net 37, all passing). Post-merge uv.lock differs from the pre-merge branch
lock only cosmetically (lock revision 3->5, pyobjc marker phrasing) — zero
version-pin changes — so the round-4 `-r5` images remain valid reconcile
subjects: all four security.yml reconcile sub-commands re-run gate-exact at
head 72f116009 against `/tmp` exports generated from the POST-merge lock and
all four print `OK: ... ships exactly the locked set` (engine 128 dists with
in-image `beartype==0.22.9` against an export emitting both 0.22.9 <'3.15' and
0.23.1 >='3.15' at export lines 132/136; hive 72; research 148; rsi 220).
`ruff check .` / `ruff format --check .`, the suite-inventory gate, and the
vulture ledger gate (`packages/*/src --min-confidence 60 --exclude
'*/third_party/*'`: 1302 reviewed == 1302 findings) are green at this head.

Verifier round (2026-10-24, head ecdc81256 = merge of db4d3eb09): the
post-db4d3eb lock resolves beartype to a SINGLE unconditional pin —
`uv export --locked --package maistro-server --extra image` emits only
`beartype==0.23.1` (no split), so the marker-split failure mode this note
documents no longer exists in the current lock; the marker-split tests remain
as script-contract pins. Executed at this head: pytest
tests/test_check_image_lock_reconciliation.py → 39 passed; scripts/
check-adr-status-language.py + git diff --check → exit 0; check-adr-index.py,
check-contract-markers.py, check-suite-inventory.py (21/21), ruff check → OK.
Independent ADR-101826-c3f1 vector replay against webauthn==3.0.1 (scratch
script outside the tree): recorded registration + assertion blobs verify with
every recorded field (packed, sc 0→1, UV, single_device, all-zero aaguid) and
I1–I6 raise the recorded messages verbatim — 8/8; the recorded wheel sha256
matches PyPI's for webauthn-3.0.1-py3-none-any.whl. Diff vs base db4d3eb adds
exactly the 5 test items this note's header records (base had lost the
f956a8142-lineage marker-split cases; the script fix itself is byte-identical
to base). Hosted `Container scan + SBOM + cosign` at this exact head was
IN_PROGRESS with zero failures in the live rollup at review time — hosted
green remains upstream-gated, not claimed here.
