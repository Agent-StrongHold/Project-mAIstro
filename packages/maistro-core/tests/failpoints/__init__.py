"""Deterministic crash/failpoint prototype lab (#883, M8-A3).

Bounded research prototype: it crosses operation x failpoint x recovery
combinations over the canonical execution spine (`tasks/execution.py`) and the
canonical external-effect boundary (`capabilities/invocation.py`), asserting
the durability properties the issue names. The machinery here is test-tree
code on purpose -- it cannot ship enabled because it cannot ship at all; see
`test_failpoint_machinery_inert.py`, which makes that property executable.
"""
