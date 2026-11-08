---
inventory-delta:
  tests/: +0
---

<!-- Net test count unchanged (79 before, 79 after). Three branch-side tests
     whose bodies encoded the pre-merge lenient parser API were rewritten to
     the merged gate's env-evaluated contract; one was renamed because its old
     name described the removed required/conditional set split:
     test_parse_expected_classifies_unconditional_and_conditional_versions_by_line
     -> test_unconditional_pin_gates_presence_inside_a_version_fork. -->

# 1836 develop-sync merge: image-lock gate resolves to develop's marker evaluator (L1836 round)

Resolving the preserved develop-sync conflict (merges of origin/develop
`37b649f36` and `09d56b6a0` into auto-1836) touched the same three files as the
previous round's merge, but this time develop's side was a full rewrite: the
upstream `#93` repair landed a stdlib PEP 508 marker evaluator
(`evaluate_marker`, `_MarkerParser`, `UnsupportedMarker`) plus an in-image
`@image-env@` dump (`parse_image_env`, `_IMAGE_ENV_SNIPPET`) so marker-forked
pins are judged against the interpreter environment they were installed for,
degrading to the old lenient rule only when the env line is missing or a
marker uses unsupported syntax. The branch's per-line required/conditional
split (`parse_expected` returning a pin-string tuple) was the same problem
solved with less information.

## Resolution

- `scripts/check-image-lock-reconciliation.py` — take develop's version
  verbatim (superset: it keeps `reconcile_variance` as a compatibility shim
  with identical semantics, `_expected_clause`, the lenient no-env
  degradation, and adds the env evaluation).
- `Dockerfile.rsi-runner` — union: develop's base-digest bump
  (`a0f57064cbd…`, matching the cleanly merged `quality/image-pins.json` pin)
  plus the branch's `SECURITY_PATCH_KEY` stamp mechanism (`ARG` + `RUN echo`,
  consumed and asserted by `.github/workflows/security.yml`, which develop
  did not touch since the merge base).
- `tests/test_check_image_lock_reconciliation.py` — the auto-merge had
  unioned develop's tests with three branch-side tests written against the
  removed tuple API; 79 collected, 76 passed, 3 failed against the resolved
  script. All three were rewritten to preserve their intent under the merged
  contract, verified `3 failed → 0 failed` in one run
  (`uv run pytest tests/test_check_image_lock_reconciliation.py -q`:
  79 passed):

1. `test_unconditional_pin_gates_presence_inside_a_version_fork` (renamed
   from `test_parse_expected_classifies_unconditional_and_conditional_versions_by_line`):
   the unconditional line still gates presence, expressed via
   `_classify_expected` + `_applicable_forks` — it applies in every
   interpreter environment, the marked line only where its marker holds.
2. `test_resolution_fork_shipped_version_reconciles`: keeps the
   run-40093845270 incident docstring; the OK-line assertion now pins the
   merged gate's reporting contract (`forks evaluated against the image
   interpreter's environment: no @image-env@ line — lenient`) instead of the
   branch's `2 marker-conditional pin(s)` counter.
3. `test_required_name_with_conditional_alternate_is_missing_only_when_absent`:
   with an env line the unconditional pin gates presence by exact pin string
   (`widgetlib==1.0 (marker: None) — applicable to the image interpreter`);
   without one the fork degrades leniently (this branch's original lenient
   assertion, now scoped to the degradation case).
