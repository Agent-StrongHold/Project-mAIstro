---
inventory-delta:
  tests/: +1
---
# claude-318-canonical-container-risk-test

Records a delta that landed on `develop` without a note, which left the trunk
failing its own `check-suite-inventory` gate (`ci.yml`) and every branch cut
from it inheriting the failure.

`067ad55` ("Classify the canonical container boundary as high risk (#318)")
added `tests/test_check_autonomous_merge.py::test_canonical_container_change_is_yellow_for_agent`
— one node ID — but no inventory note, so `tests/` collected 1838 against a
recorded 1837. Confirmed by bisection: `626172a` and `e5e747e` (#332/#505,
which did carry its note) both pass the gate; the merge carrying `067ad55`
does not.

This note only records the count. The test itself is #318's and is left
untouched.
