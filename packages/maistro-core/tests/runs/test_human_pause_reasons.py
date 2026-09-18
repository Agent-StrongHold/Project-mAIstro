"""One declared set of human pause reasons, and both readers bound to it (#545).

Two hand-written allowlists -- the durable graph executor's `_is_human_pause`
and the schedule consumer's yield disposition -- each named two reasons while
production nodes raised four. `human.review_and_edit` and
`human.delegate_to_role` therefore parked as WAITING on *both* paths: recorded
as "the system owes a retry" when the truth was "a person owes an answer".

Nothing failed when the set was wrong, which is why it stayed wrong. So the
tests here are structural as well as behavioural: the behavioural ones pin
what the readers now decide, and the structural one walks the node package's
AST and fails when a node pauses for a reason the shared set does not declare.
A test that only listed today's four reasons would pass again the moment a
fifth was added and forgotten -- the exact failure it exists to catch.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

import maistro.graph.nodes.base as base
from maistro.graph.durable_runs.executor import _is_human_pause
from maistro.graph.nodes.base import (
    HUMAN_PAUSE_REASONS,
    PAUSE_REASON_OWNERS,
    NodeResult,
)
from maistro.runs.consumption import _awaits_human_answer
from maistro.runs.model import NodeRun, RunStatus
from maistro.runs.reconciliation import _parked_run_status

#: SPEC-082926-d90e declares `contracts: [behavioral]`, and ADR-032 says a
#: document claiming a contract kind names a test carrying that marker. It named
#: these two files and neither carried one, so the claim had no evidence (#345).
pytestmark = [pytest.mark.contract("behavioral")]


#: Located through the imported module, not a path relative to this test, so
#: the guard cannot start silently scanning an empty directory if either tree
#: is rearranged.
NODE_DIR = pathlib.Path(base.__file__).resolve().parent

#: Every reason a person is owed an action. Named here so a reader of this
#: file can see what the guard is guarding, but the structural assertion
#: compares against the *imported* sets, never against this list alone.
EXPECTED_HUMAN = {
    "awaiting_human_answer",
    "awaiting_human_approval",
    "awaiting_human_review",
    "awaiting_role_delegate",
}

#: Pauses that wait on a system -- a remote agent, a harness, a polled API.
#: WAITING is the right record for these, and that is a decision the table
#: states, not a default: the structural guard below is what makes it one.
EXPECTED_SYSTEM = {
    "awaiting_remote_delegation",
    "awaiting_harness",
    "waiting_on_jira_subtasks",
}


def _paused_reasons_raised_by_nodes() -> dict[str, set[str]]:
    """Every constant name each node module hands to `pause_until`.

    AST, not a regex: the reason is the call's first positional argument, and
    a regex over the file would also match the word in a docstring or comment,
    which is how a survey of this same package once counted prose as code.
    """
    found: dict[str, set[str]] = {}
    for path in sorted(NODE_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call):
                continue
            func = call.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name != "pause_until" or not call.args:
                continue
            first = call.args[0]
            if isinstance(first, ast.Name):
                found.setdefault(path.name, set()).add(first.id)
            elif isinstance(first, ast.Constant):
                found.setdefault(path.name, set()).add(repr(first.value))
    return found


class TestTheSetIsDeclaredOnce:
    def test_the_human_set_holds_every_human_reason(self) -> None:
        assert set(HUMAN_PAUSE_REASONS) == EXPECTED_HUMAN

    def test_the_table_classifies_every_system_reason(self) -> None:
        system = {r for r, owner in PAUSE_REASON_OWNERS.items() if owner == "system"}
        assert system == EXPECTED_SYSTEM

    def test_every_reason_states_an_owner_the_readers_understand(self) -> None:
        """A third owner value would park silently, which is the whole defect."""
        assert set(PAUSE_REASON_OWNERS.values()) <= {"human", "system"}
        assert set(PAUSE_REASON_OWNERS) == EXPECTED_HUMAN | EXPECTED_SYSTEM

    @pytest.mark.ac("SPEC-082926-d90e/AC-5")
    def test_no_node_pauses_for_an_undeclared_reason(self) -> None:
        """A new pausing node must classify itself, not default to WAITING.

        Every `pause_until` call in the package passes a *constant* imported
        from `.base`, and every one of those constants names a reason
        `PAUSE_REASON_OWNERS` classifies -- as human, or explicitly as system. A bare
        string literal fails here too: a literal is exactly how four reasons
        diverged from the two the readers knew, with nothing failing meanwhile.

        This guard found three reasons on its first run that the set it was
        written against did not have. They turned out to be system waits, so
        the readers' answer was right by luck; the point is that nothing said
        so until something checked.
        """
        raised = _paused_reasons_raised_by_nodes()
        assert raised, "no pause_until call found; this guard would pass vacuously"

        undeclared: dict[str, set[str]] = {}
        for module, names in raised.items():
            for name in names:
                value = getattr(base, name, None) if not name.startswith(("'", '"')) else None
                if value is None or value not in PAUSE_REASON_OWNERS:
                    undeclared.setdefault(module, set()).add(name)
        assert not undeclared, (
            "these nodes pause for a reason PAUSE_REASON_OWNERS does not name, so both "
            f"readers silently fall back to WAITING for them: {undeclared}"
        )


class TestBothReadersAgree:
    """The two paths a HITL node can execute on must reach the same answer."""

    @pytest.mark.ac("SPEC-082926-d90e/AC-5")
    @pytest.mark.parametrize("reason", sorted(EXPECTED_HUMAN))
    def test_every_human_reason_is_a_human_pause_on_both_paths(self, reason: str) -> None:
        result = NodeResult(success=True, metadata={"paused_reason": reason})

        assert _is_human_pause(result) is True
        assert _awaits_human_answer(result) is True

    @pytest.mark.parametrize(
        "reason", [*sorted(EXPECTED_SYSTEM), "polling_provider", "", "awaiting_human"]
    )
    def test_a_system_wait_is_not_a_human_pause_on_either_path(self, reason: str) -> None:
        """Every declared system reason, plus `awaiting_human` -- a prefix of two.

        Membership, not `startswith`: a substring test would take that prefix
        and every other near-miss as a human pause.
        """
        result = NodeResult(success=True, metadata={"paused_reason": reason})

        assert _is_human_pause(result) is False
        assert _awaits_human_answer(result) is False

    def test_absent_metadata_is_not_a_human_pause(self) -> None:
        result = NodeResult(success=True)

        assert _is_human_pause(result) is False
        assert _awaits_human_answer(result) is False


class TestTheRunInheritsThePause:
    """A Run parks in the state its last NodeRun parked in, not always WAITING."""

    def _node_run(self, status: RunStatus) -> NodeRun:
        return NodeRun(run_id="r", node_id="n", ordinal=1, status=status)

    @pytest.mark.ac("SPEC-082926-d90e/AC-6")
    def test_a_paused_node_run_parks_its_run_paused(self) -> None:
        assert _parked_run_status(self._node_run(RunStatus.PAUSED)) is RunStatus.PAUSED

    @pytest.mark.ac("SPEC-082926-d90e/AC-6")
    def test_a_waiting_node_run_parks_its_run_waiting(self) -> None:
        assert _parked_run_status(self._node_run(RunStatus.WAITING)) is RunStatus.WAITING

    @pytest.mark.parametrize("status", [RunStatus.RUNNING, RunStatus.CREATED])
    def test_any_other_status_falls_back_to_waiting(self, status: RunStatus) -> None:
        """`_pause_node_run` can return a NodeRun it did not transition.

        Forwarding that status blindly would let a path that only ever means
        "park" transition the Run somewhere else entirely.
        """
        assert _parked_run_status(self._node_run(status)) is RunStatus.WAITING
