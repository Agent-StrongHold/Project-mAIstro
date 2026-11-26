---
inventory-delta:
  tests/: +1
---

# cursor-m1-b-p4b-timeout-marker-docs-8551

Registering the ``timeout`` pytest marker in root ``pyproject.toml`` (so hive
CI's system-python step can collect ``@pytest.mark.timeout`` under
``--strict-markers``) adds one parametrized node to
``tests/test_pytest_marker_docs.py::test_axis_markers_document_only_their_registered_values[timeout]``.
The case skips — ``timeout`` is not a fixed-axis marker — but still counts as
a collected node ID.
