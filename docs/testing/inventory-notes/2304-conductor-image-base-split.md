---
inventory-delta:
  tests/: +4
---

# Issue #2304 Conductor image builder/runtime base split

The Conductor image repair for #2304 splits the dependabot base bump across
stages: `pybuild` stays on the registered `python:3.13.16-slim-bookworm` pin
(the identity-contract interpreter the build smoke asserts), `runtime-apt`
takes the `python:3.15.0-slim-bookworm` bump, and the final stage grafts the
builder's exact CPython 3.13.16 installation so the copied venv's interpreter
symlinks resolve without a managed download.

`tests/test_hive_conductor_image_split.py` adds four tests holding that
structure closed: the builder pin against its `quality/image-pins.json` row
(and the venv still created from the system 3.13 interpreter), the runtime
digest registered and deliberately different from the builder base, the graft
(binary + libpython + stdlib + `ldconfig`) present in the shipped stage, and
the build-time identity smoke untouched (`(3, 13, 16)` plus the
bip-utils/coincurve/pynacl ARG pins). The first and third tests fail against
the pre-repair Dockerfile — the state that shipped the `AssertionError:
3.13.15` CI failures — so they name the regression they prevent.
