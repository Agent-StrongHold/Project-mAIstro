---
inventory-delta:
  tests/: +9
---
# auto-325 repair round: marker-split pins in the image-lock reconciliation gate

Nine additions to `tests/test_check_image_lock_reconciliation.py`, each pinning
a facet of one defect the L325 security-gate repair surfaced: cc549e3c5's
fastmcp bump split `beartype` across a `python_full_version` marker
(0.22.9 / 0.23.1), and `uv export` therefore emits two rows for one
distribution. The gate's name-keyed bookkeeping kept only one row per name, so
a correctly-built image was reported as a version skew (or as an un-locked
extra) depending on which row survived — a deterministic red for every
`containers`-job reconciliation after that lock change.

The script now (a) dumps the image interpreter's own `python_full_version` as
the first line of the `docker run` dump, (b) collects every marker-carrying row
per name, and (c) in the skew check compares against the pin whose marker
applies to the dumped interpreter — falling back to the lenient conditional
treatment only when the applicable pin cannot be determined. Every row keeps a
version check that can fire: the wrong build for the image's python is still a
named version mismatch.

Tests:

- `test_parse_marker_variants_finds_only_multi_version_names` — the split
  detection; single-row names (conditional or not) are not variants.
- `test_image_python_version_reads_the_dump_header` /
  `test_parse_actual_ignores_the_python_version_header` — the dump header is
  the version source and never a pin.
- `test_marker_split_image_ships_the_applicable_pin_reconciles` — the live
  beartype case on a 3.13 interpreter reconciles (was: red).
- `test_marker_split_selects_by_the_image_python_version` — the same lock
  reconciles a 3.15+ image against the other row.
- `test_marker_split_wrong_pin_for_the_image_python_is_a_skew` — strictness
  preserved: the wrong build is a named mismatch.
- `test_marker_split_with_unevaluatable_marker_stays_lenient` — old-format
  dumps fall back to gating nothing, not to guessing a row.
- `test_marker_bound_without_a_patch_level_compares_zero_padded` — PEP 508
  release-tuple comparison (`'3.15'` binds `(3, 15, 0)`).
- `test_marker_without_python_clauses_selects_unconditionally` — platform-only
  splits and markerless rows select directly; missing dump version is the
  `None` leniency signal.

Pre-fix demonstration: against the pre-fix script, the live scenario
(`uv export` of this tree + the rebuilt research image) failed with
`version mismatch : beartype==0.22.9 (image) != beartype==0.23.1` and then
`in image, not locked : beartype==0.22.9`; both new reconcile tests fail on the
pre-fix module with the same two shapes.
