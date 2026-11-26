---
inventory-delta:
  tests/: +5
---
# 330-image-lock-recon-marker-fork

Five additions in `tests/test_check_image_lock_reconciliation.py`; nothing
removed. They pin the marker-fork behaviour the #330 containers-job repair
depends on: this lane's own `uv lock --upgrade-package` (687b3830e) forked
beartype across `python_full_version` markers (0.22.9 for < '3.15', 0.23.1
for >= '3.15'), the `uv export` the reconcile gate reads then lists BOTH
pins, and the gate's name-keyed bookkeeping collapsed them — `parse_expected`
kept only the last variant per name and the comparison dict picked an
arbitrary winner, so a py3.13 image carrying the lock's correct beartype
0.22.9 failed `Reconcile installed packages to uv.lock` and redrew the whole
"Container scan + SBOM + cosign" job. Reproduced locally against all four
images built from this tree before the fix (engine: `beartype==0.22.9
(image) != beartype==0.23.1`), green after it.

**`test_parse_expected_keeps_every_marker_forked_variant_of_a_name` (+1).**
The parse itself: a forked name contributes every variant to the conditional
set instead of keeping only the last one a dict slot saw.

**`test_marker_forked_variants_image_matching_one_variant_reconciles` and
`..._other_variant_also_reconciles` (+2).** The #330 regression end to end,
in the export's exact shape: an image installing either locked variant of a
forked name reconciles; neither variant is disowned by hash order.

**`test_marker_forked_variants_version_matching_neither_is_a_skew` (+1).**
The gate keeps its teeth: an installed version no locked variant names is
still one "version mismatch" line naming both variants — not a missing/extra
pair, and not silently accepted.

**`test_reconcile_variance_is_order_independent_over_forked_variants` (+1).**
Pure-logic pin on the extracted `reconcile_variance`: 50 shuffled
invocations agree that a matching variant passes and a non-matching one
fails, so the verdict cannot drift with set iteration order again.
