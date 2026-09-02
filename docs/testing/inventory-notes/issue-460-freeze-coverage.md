---
inventory-delta:
  tests/: +8
---

# Freeze-checker branch-coverage tests (#460)

Adds eight root `tests/` node IDs in
`tests/test_m1_convergence_freeze_branch_coverage.py` covering the checker's
previously-unmeasured defensive surface required by the diff-coverage gate:
the `_provenance` loader guards (cached-module return, unloadable-spec
refusal, sys.modules cleanup on exec failure), the `_ontology`
trusted-base fallback, `_module_name`'s hive-conductor path resolution,
`_changed_python_pairs`'s rename/copy/add/skip classification and its
git-failure refusal, and `shared_owner_failures`' tolerance of a missing
base blob.
