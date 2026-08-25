"""Tests for the plugin that settles the `passing` rung (#257).

`scripts/ac_outcome_plugin.py` writes the map of which acceptance criteria have
a passing test. Every criterion's rung above `covered` rests on it, and through
that so does `design_coverage` and the floor every PR is measured against — and
until this file it had no test at all. That is the sharpest case of #257's
finding: the gates are the least-gated code in the repository.

The three behaviours worth pinning are the ones a plausible implementation gets
wrong: a skip is not a pass, one failing test sinks a criterion however many
others claim it, and a fixture error counts even though it is not the call
phase.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ac_outcome_plugin.py"


@pytest.fixture
def plugin():
    """A freshly imported plugin per test.

    Reimported rather than reset, because the module keeps its two maps at
    module scope. A shared instance would let one case's outcomes decide
    another's, which is exactly the accumulation bug these tests exist to
    detect.
    """
    spec = importlib.util.spec_from_file_location("ac_outcome_plugin", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _Marker:
    def __init__(self, *args):
        self.args = args


class _Item:
    def __init__(self, nodeid, *ac_ids):
        self.nodeid = nodeid
        self._markers = [_Marker(*ac_ids)] if ac_ids else []

    def iter_markers(self, name):
        return self._markers if name == "ac" else []


class _Report:
    def __init__(self, nodeid, outcome):
        self.nodeid = nodeid
        self.outcome = outcome


def _run(plugin, items, reports):
    plugin.pytest_collection_modifyitems(items)
    for report in reports:
        plugin.pytest_runtest_logreport(report)


class TestClaims:
    def test_a_marked_test_claims_its_ids(self, plugin):
        plugin.pytest_collection_modifyitems([_Item("t.py::a", "S/AC-1", "S/AC-2")])
        assert plugin._claims == {"t.py::a": ["S/AC-1", "S/AC-2"]}

    def test_an_unmarked_test_claims_nothing(self, plugin):
        plugin.pytest_collection_modifyitems([_Item("t.py::a")])
        assert plugin._claims == {}

    def test_a_report_for_an_unclaiming_test_is_ignored(self, plugin):
        _run(plugin, [], [_Report("t.py::a", "passed")])
        assert plugin._passing == {}


class TestPassing:
    def test_a_passing_test_makes_its_criterion_passing(self, plugin):
        _run(plugin, [_Item("t.py::a", "S/AC-1")], [_Report("t.py::a", "passed")])
        assert plugin._passing == {"S/AC-1": True}

    @pytest.mark.ac("ADR-082526-9fa2/AC-1")
    def test_a_skip_is_not_a_pass(self, plugin):
        """The plugin's central claim: an environment-gated test that never ran
        is not evidence the criterion holds. Counting a skip as a pass would
        make every criterion behind an unavailable service read as proven."""
        _run(plugin, [_Item("t.py::a", "S/AC-1")], [_Report("t.py::a", "skipped")])
        assert plugin._passing == {"S/AC-1": False}

    def test_a_failure_is_not_a_pass(self, plugin):
        _run(plugin, [_Item("t.py::a", "S/AC-1")], [_Report("t.py::a", "failed")])
        assert plugin._passing == {"S/AC-1": False}

    @pytest.mark.ac("ADR-082526-9fa2/AC-2")
    def test_one_failing_test_sinks_a_criterion_others_claim(self, plugin):
        """`and`, not assignment. Written as assignment, a later passing test
        claiming the same id would overwrite the failure and the criterion
        would read proven while a test for it was red."""
        _run(
            plugin,
            [_Item("t.py::a", "S/AC-1"), _Item("t.py::b", "S/AC-1")],
            [_Report("t.py::a", "failed"), _Report("t.py::b", "passed")],
        )
        assert plugin._passing == {"S/AC-1": False}

    def test_order_does_not_matter_to_that(self, plugin):
        _run(
            plugin,
            [_Item("t.py::a", "S/AC-1"), _Item("t.py::b", "S/AC-1")],
            [_Report("t.py::b", "passed"), _Report("t.py::a", "failed")],
        )
        assert plugin._passing == {"S/AC-1": False}

    @pytest.mark.ac("ADR-082526-9fa2/AC-3")
    def test_a_fixture_error_sinks_the_criterion_too(self, plugin):
        """Every phase reports through the same hook, so a setup that errored
        arrives as a non-passed report for the same nodeid. A test whose
        fixture blew up demonstrated nothing, and the call phase that never
        ran cannot say otherwise."""
        _run(
            plugin,
            [_Item("t.py::a", "S/AC-1")],
            [_Report("t.py::a", "failed"), _Report("t.py::a", "passed")],
        )
        assert plugin._passing == {"S/AC-1": False}

    def test_every_phase_passing_leaves_it_passing(self, plugin):
        _run(
            plugin,
            [_Item("t.py::a", "S/AC-1")],
            [_Report("t.py::a", "passed")] * 3,
        )
        assert plugin._passing == {"S/AC-1": True}


class TestOutput:
    def test_claimed_lists_every_id_whatever_the_outcome(self, plugin, tmp_path, monkeypatch):
        """`claimed` is the denominator and `passing` the numerator, so a
        failing criterion has to stay in the first while leaving the second."""
        out = tmp_path / "ac.json"
        monkeypatch.setenv("AC_OUTCOME_JSON", str(out))
        _run(
            plugin,
            [_Item("t.py::a", "S/AC-1"), _Item("t.py::b", "S/AC-2")],
            [_Report("t.py::a", "passed"), _Report("t.py::b", "failed")],
        )
        plugin.pytest_sessionfinish(None, 0)
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["claimed"] == ["S/AC-1", "S/AC-2"]
        assert payload["passing"] == ["S/AC-1"]

    @pytest.mark.ac("ADR-082526-9fa2/AC-4")
    def test_without_the_env_var_nothing_is_written(self, plugin, tmp_path, monkeypatch):
        """The plugin has to be inert in an ordinary run. Writing to a default
        path would let a plain `pytest` overwrite the map a measured run
        produced."""
        monkeypatch.delenv("AC_OUTCOME_JSON", raising=False)
        _run(plugin, [_Item("t.py::a", "S/AC-1")], [_Report("t.py::a", "passed")])
        plugin.pytest_sessionfinish(None, 0)
        assert list(tmp_path.iterdir()) == []

    def test_a_criterion_claimed_but_never_reported_is_not_passing(
        self, plugin, tmp_path, monkeypatch
    ):
        """Collected and then deselected, or the session died before it ran.
        Either way no report arrived, and absence is not evidence."""
        out = tmp_path / "ac.json"
        monkeypatch.setenv("AC_OUTCOME_JSON", str(out))
        plugin.pytest_collection_modifyitems([_Item("t.py::a", "S/AC-1")])
        plugin.pytest_sessionfinish(None, 0)
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert payload["claimed"] == ["S/AC-1"]
        assert payload["passing"] == []
