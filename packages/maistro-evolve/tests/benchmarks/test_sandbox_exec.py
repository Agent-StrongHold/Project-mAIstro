"""Fail-closed contract for the evaluator's isolated check.

`run_function_checks` is the only place `maistro-evolve` executes candidate
Python, and since #76 it does so through the canonical `maistro.sandbox`
selector instead of the retired Docker adapter. The selector refuses
(`NoSuitableBackendError`) when no backend satisfies the workload policy --
a Kata-less / bubblewrap-only host. That refusal must be the *same* fail-closed
verdict as Docker being absent: the check returns ``(False, ...)`` and candidate
code never runs on the host. Before the #76 converge the refusal escaped the
except clause and propagated to `run_swebench`, which scored the sample zero
for the wrong reason and, on a selector-less host, crashed the evaluator.
"""

from __future__ import annotations

import sys
from typing import Any

from maistro_evolve.benchmarks.sandbox_exec import run_function_checks

_CODE = """
def add(a, b):
    return a + b
"""

_CASES: list[tuple[list[Any], Any]] = [([1, 2], 3)]


async def test_selector_refusal_fails_closed(monkeypatch: Any) -> None:
    """A `NoSuitableBackendError` from the canonical selector is a fail-closed
    verdict, not a propagating exception."""
    from maistro.sandbox.selector import NoSuitableBackendError

    async def refusing_create_sandbox(*args: Any, **kwargs: Any) -> Any:
        raise NoSuitableBackendError("no backend on this host")

    monkeypatch.setattr("maistro.tools.sandbox.canonical.create_sandbox", refusing_create_sandbox)

    passed, detail = await run_function_checks(_CODE, "add", _CASES)

    assert passed is False
    assert "isolated sandbox unavailable" in detail


async def test_selector_import_gap_fails_closed(monkeypatch: Any) -> None:
    """A host without the canonical `maistro.sandbox` surface also fails
    closed (the pre-#76 behaviour for a host without Docker). A `None` entry
    in `sys.modules` makes the in-function import raise `ImportError`."""

    monkeypatch.setitem(sys.modules, "maistro.tools.sandbox.canonical", None)

    passed, detail = await run_function_checks(_CODE, "add", _CASES)

    assert passed is False
    assert "isolated sandbox unavailable" in detail
