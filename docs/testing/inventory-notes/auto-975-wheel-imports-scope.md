---
inventory-delta:
  tests/: +1
---

# Wheel-imports gate script changes must run the wheel-imports leg (#975 salvage)

`scripts/ci_merge_group_scope.py` classifies changed paths into merge-group
legs. The wheel-imports validation lives inside the `wheel_imports` job, which
invokes **two** gate scripts: `scripts/verify-minimum-dependencies.py` and
`scripts/verify-wheel-imports.py`. Only the first was classified as a trigger,
so a candidate touching only the wheel-import verifier skipped its own
end-to-end validation at the merge-queue SHA — the same self-skip shape the
minimum-dependencies trigger comment already described.

The change adds `scripts/verify-wheel-imports.py` to that trigger set and one
test, `test_wheel_import_verifier_change_runs_wheel_imports_leg`, pinning the
contract: classifying a change to that script alone fires `wheel_imports` and
`docker_build`, not `postgres` — mirroring the existing
minimum-dependencies test beside it.
