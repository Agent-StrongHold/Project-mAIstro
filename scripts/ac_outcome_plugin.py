"""pytest plugin: record which acceptance criteria have a passing test.

`scripts/check-ac-state.py` needs the *passing* rung settled, and the only
honest way to settle it is to run the tests and read the outcomes. Parsing
pytest's terminal summary would work until the first test id containing a
space; a plugin reads the report objects directly.

A criterion is passing only when every test claiming it passed. A skip proves
nothing — an environment-gated test that never ran is not evidence the
criterion holds — so a skip leaves the id off the list rather than counting as
a pass, and setup/teardown are folded in for the same reason: a test whose
fixture errored demonstrated nothing either.

Activated by `check-ac-state.py --run-tests`, which writes JSON to the path in
`AC_OUTCOME_JSON`. Nothing registers this as an entry point, so it never loads
during an ordinary test run.
"""

from __future__ import annotations

import json
import os
from typing import Any

# nodeid -> the AC ids that test claims, built once at collection.
_claims: dict[str, list[str]] = {}
# AC id -> still-unbroken. Written by every phase of every claiming test.
_passing: dict[str, bool] = {}


def pytest_collection_modifyitems(items: list[Any]) -> None:
    for item in items:
        ids = [str(arg) for marker in item.iter_markers(name="ac") for arg in marker.args]
        if ids:
            _claims[item.nodeid] = ids


def pytest_runtest_logreport(report: Any) -> None:
    ids = _claims.get(report.nodeid)
    if not ids:
        return
    # "passed" for setup/teardown, `report.passed` for the call phase — a test
    # that was skipped reports outcome "skipped" here and so sinks the id.
    ok = report.outcome == "passed"
    for ac_id in ids:
        # `and`, not assignment: one failing test sinks the criterion, and a
        # later passing test claiming the same id must not paper over it.
        _passing[ac_id] = _passing.get(ac_id, True) and ok


def pytest_sessionfinish(session: Any, exitstatus: int) -> None:
    path = os.environ.get("AC_OUTCOME_JSON")
    if not path:
        return
    payload = {
        "claimed": sorted({ac for ids in _claims.values() for ac in ids}),
        "passing": sorted(ac for ac, ok in _passing.items() if ok),
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
