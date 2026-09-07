---
inventory-delta:
  tests/: +8
---
# m4-391 — registered pytest markers documented and checked

#391 closed the gap between pytest configuration and its documentation: the
`ac` marker (1300+ uses, drives the acceptance-state/design-coverage gate)
was absent from CONTRIBUTING, which documented only `contract` and `scope`.
CONTRIBUTING's Tests section is now a marker table — meaning, consumer,
CI effect, AC-linkage examples with rung behavior — and pytest runs with
`--strict-markers` so unknown markers fail collection instead of passing as
inert decoration.

The +7 node IDs are all in `tests/test_pytest_marker_docs.py` (new):

- Every registered marker is documented; every documented marker is
  registered (both directions of the #391 defect).
- Each table row carries meaning/consumer/CI-effect columns, and every
  consumer named in the table exists (a gate script or a `pytest -m`
  selection).
- addopts really carries `--strict-markers`, as the docs claim.
- The contract/scope examples use only the axis values pyproject itself
  declares (one parametrized case each).
