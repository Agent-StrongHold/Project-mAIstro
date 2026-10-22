---
inventory-delta:
  tests/: +5
---

# 1572-wheel-sibling-constraint-pinning

Five node IDs, added on this branch during the #1572 coverage-gate repair, all
in `tests/test_verify_wheel_imports.py`. The diff-coverage gate failed the
branch's own change to `scripts/verify-wheel-imports.py` (the sibling-wheel
constraint pinning): the changed lines inside `check()` and
`_wheel_dist_name()` had no producer coverage, because every existing test in
that file deliberately routes around `check()` ("building and installing wheels
takes minutes").

`TestTheSiblingConstraintPin` closes that hole without a real build:

- `test_check_pins_every_sibling_wheel_to_its_local_artifact` drives `check()`
  end-to-end through a fake `uv` shim (millisecond `venv` + offline wheel
  unpack) and a real minimal wheel, then asserts from the shim's receipt that
  the installer was handed `--constraints` and that its content pins
  `dummy @ file://<exact wheel>` — the exact regression the change fixes (uv
  breaking a same-version tie toward a stale PyPI snapshot). The test was
  proven sensitive: against a copy of the script with the constraint block
  removed, the install argv carries no `--constraints` and the assertions fail.
- `test_check_fails_closed_when_the_wheel_was_never_built` holds the
  missing-wheel refusal (no install attempted, receipt absent).
- Three parametrized `_wheel_dist_name` cases pin the PEP 503 normalization
  (underscored dist → dashed name, dots/case collapse, underscore/case
  collapse).

Plain unit tests over `subprocess` + `zipfile`; no network, no services, no
skips — exactly +5 collected node IDs in the `tests/` suite. No other suite
moved.
