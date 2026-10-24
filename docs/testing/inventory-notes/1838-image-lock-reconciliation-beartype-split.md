---
inventory-delta:
  tests/: +3
---
# 1838-image-lock-reconciliation-beartype-split

## What moved

CI-repair for the L1838 lane (issue #1838, branch `auto-1838`): the
`security.yml` `containers` job — "Container scan + SBOM + cosign" — failed at
head `08dfd6f25b0fec7e50f40e1176c1cd96ece61a11` in its "Reconcile installed
packages to uv.lock" step (CI run `40097563262`, job `120882902208`):

```
image maistro-engine:pr-2269 does NOT reconcile to the lock:
  version mismatch     : beartype==0.22.9 (image) != beartype==0.23.1
```

The image was right and the gate was wrong. The #1838 round-5 lock change
upgraded `fastmcp` 4.0.11→4.1.3, whose resolution splits `beartype` by
interpreter (`0.22.9 ; python_full_version < '3.15'`, `0.23.1 ; >= '3.15'`)
via `py-key-value-aio` → beartype. `uv export` lists both entries; pip's marker
evaluation on the image's python 3.13.16 correctly installs `0.22.9`. But
`scripts/check-image-lock-reconciliation.py` keyed its expected pins by
canonical name, so the later export line overwrote the earlier one and the
gate compared the image's legitimate `0.22.9` against the `0.23.1` alternative
only — a red reconciliation for an image that shipped exactly the locked set.

`beartype` is the only multi-version name across all four CI reconciliation
exports on this tree (engine, hive-conductor, research, rsi-runner), so fixing
the gate's parser covers every invocation of the step.

## Repair

`parse_expected` now returns conditional pins grouped by name (every
alternative kept), and the reconcile step accepts a shipped split name against
ANY of its locked alternatives — the image's interpreter decides which marker
applies, and each alternative is a version the lock prescribes for some
environment the scanners audit. A version the lock never named is still a
named version mismatch, reporting every alternative it was measured against.
The gate's documented lenient-conditional contract ("matches either way — its
version is still checked when it does ship") is unchanged in strength for
single-version names; the defect was the last-line-wins collapse, not the
leniency.

## The +3 node IDs

`tests/test_check_image_lock_reconciliation.py`:

- `test_parse_expected_keeps_every_version_of_a_python_version_split` — the
  split export (hash continuations included) parses to both alternatives.
- `test_python_version_split_reconciles_the_interpreter_appropriate_pin` —
  the CI regression reduced: split lock + image on the `< 3.15` side
  reconciles exit 0.
- `test_python_version_split_still_rejects_a_version_the_lock_never_named` —
  the lenient comparison is not a waive: `0.19.0` (never locked) skews,
  naming both alternatives.

One existing test updated in place (no count change):
`test_parse_expected_splits_conditional_from_required_pins` asserts the new
by-name conditional mapping.

## Structural regression proof

All four split tests fail against the pre-fix parser (old parse collapses the
beartype alternative set to the last line; old reconcile compares against
`0.23.1` only) and pass against the fixed script.
