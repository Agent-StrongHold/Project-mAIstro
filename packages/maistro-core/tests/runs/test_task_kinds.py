"""A submitted task resolves to a node kind that can actually run it (#41).

The property under test is not "the table has the right rows" — the table lives
in `maistro.agents.intents` and has its own tests. It is that the mapping is
*total* and *executable*: every task, however sparsely described, resolves to a
kind the node registry knows, with parameters the node's own input schema
accepts. A mapping that resolved to a plausible-looking kind nothing could run
would reintroduce exactly the half-truth admission exists to refuse.
"""

from __future__ import annotations

import pytest

from maistro.agents.intents import IntentRegistry
from maistro.graph.nodes import get_node, list_kinds
from maistro.runs.task_kinds import (
    DEFAULT_WORK_NAME,
    DELEGATE_NODE_KIND,
    resolve_direct_work,
)


def test_the_kind_it_resolves_to_is_registered() -> None:
    assert DELEGATE_NODE_KIND in list_kinds()


@pytest.mark.parametrize(
    ("task_type", "expected_agent"),
    [
        ("code", "artificer"),
        ("code_gen", "mason"),
        ("search", "ranger"),
        ("creative", "scribe"),
    ],
)
def test_task_type_resolves_through_the_intent_table(task_type: str, expected_agent: str) -> None:
    work = resolve_direct_work(description="do the thing", task_type=task_type)

    assert work.node_type == DELEGATE_NODE_KIND
    assert work.agent_name == expected_agent
    assert work.parameters["to_agent"] == expected_agent


def test_unknown_task_type_still_resolves() -> None:
    """Totality is the point: admission must never fail for lack of a row."""
    work = resolve_direct_work(description="do the thing", task_type="no-such-type")

    assert work.agent_name == "artificer"


@pytest.mark.parametrize("task_type", [None, "", "   "])
def test_missing_task_type_still_resolves(task_type: str | None) -> None:
    work = resolve_direct_work(description="do the thing", task_type=task_type)

    assert work.agent_name == "artificer"


def test_explicit_agent_id_beats_the_table() -> None:
    """A submitter who named an agent gets that agent, not the table's guess."""
    work = resolve_direct_work(description="do the thing", task_type="code", agent_id="scribe")

    assert work.agent_name == "scribe"


def test_blank_agent_id_falls_back_to_the_table() -> None:
    work = resolve_direct_work(description="do it", task_type="code", agent_id="   ")

    assert work.agent_name == "artificer"


def test_an_injected_registry_is_used() -> None:
    registry = IntentRegistry({"bespoke": "davinci"})

    work = resolve_direct_work(description="paint", task_type="bespoke", registry=registry)

    assert work.agent_name == "davinci"


def test_parameters_validate_against_the_node_input_schema() -> None:
    """The whole claim of this module: these parameters are executable."""
    work = resolve_direct_work(
        description="ship it", task_type="code", from_agent="conductor", timeout_seconds=60
    )
    node_cls = get_node(work.node_type)

    inputs = node_cls.input_schema.model_validate(work.parameters)

    assert inputs.to_agent == "artificer"
    assert inputs.task == "ship it"
    assert inputs.from_agent == "conductor"
    assert inputs.timeout_seconds == 60


def test_timeout_is_omitted_rather_than_guessed() -> None:
    """No timeout given means the node's own default applies, not ours."""
    work = resolve_direct_work(description="ship it")

    assert "timeout_seconds" not in work.parameters


def test_name_is_the_first_line_of_the_description() -> None:
    work = resolve_direct_work(description="Fix the parser\n\nlong detail follows")

    assert work.name == "Fix the parser"


def test_long_name_is_bounded() -> None:
    work = resolve_direct_work(description="x" * 500)

    assert len(work.name) <= 80


@pytest.mark.parametrize("description", ["", "   ", "\n\n"])
def test_empty_description_still_yields_a_name(description: str) -> None:
    work = resolve_direct_work(description=description)

    assert work.name == DEFAULT_WORK_NAME
