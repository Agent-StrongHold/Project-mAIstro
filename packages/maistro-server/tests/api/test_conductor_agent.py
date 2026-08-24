"""The roster floor a deployment with no agents still has (#142).

`Conduit.route_request` answers "No agents available." with an empty `agents`
map, and this server has never built any. `run_task` needs no roster, which is
why the OpenAI door works today on deployments that configured none — so the
floor is what keeps routing through the Conduit from turning every one of those
turns into a refusal.

These tests are about the seam, not about `run_task`: what reaches it, what
comes back, and what happens when it raises.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from maistro.agents.types import ConductorOutput, LLMProviderError
from maistro.types.intent import Intent
from maistro_server.conductor_agent import (
    CONDUCTOR_AGENT_NAME,
    ConductorAgent,
    _last_user_message,
    _tier_kwargs,
)


def _messages(*pairs: tuple[str, str]) -> list[dict[str, Any]]:
    return [{"role": role, "content": content} for role, content in pairs]


class TestWhatReachesTheConductor:
    async def test_the_last_user_message_is_the_description(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`run_task` takes one description, not a conversation. The classifier
        upstream saw every message; this is the part that can be handed on."""
        run_task = AsyncMock(return_value=ConductorOutput(final_answer="ok", success=True))
        monkeypatch.setattr("maistro_server.conductor_agent.run_task", run_task)

        await ConductorAgent().handle(
            _messages(("system", "be helpful"), ("user", "first"), ("user", "second"))
        )

        assert run_task.await_args is not None
        assert run_task.await_args.args[0].description == "second"

    async def test_the_classifiers_tier_reaches_the_task(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The point of routing through the Conduit at all, on this path. Before
        #142 every turn ran at the default tier because nothing classified it."""
        run_task = AsyncMock(return_value=ConductorOutput(final_answer="ok", success=True))
        monkeypatch.setattr("maistro_server.conductor_agent.run_task", run_task)

        await ConductorAgent().handle(
            _messages(("user", "hi")), intent=Intent(task_type="code", tier=3)
        )

        assert run_task.await_args is not None
        assert run_task.await_args.args[0].tier == 3

    async def test_a_turn_with_no_user_message_answers_rather_than_calling(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Nothing to run. Answering is the right shape — `run_task` would be
        handed an empty description and asked to plan work nobody described."""
        run_task = AsyncMock()
        monkeypatch.setattr("maistro_server.conductor_agent.run_task", run_task)

        response = await ConductorAgent().handle(_messages(("system", "be helpful")))

        assert run_task.await_count == 0
        assert response.content == "No message provided."


class TestWhatComesBack:
    async def test_the_final_answer_is_the_content(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "maistro_server.conductor_agent.run_task",
            AsyncMock(return_value=ConductorOutput(final_answer="42", success=True)),
        )

        response = await ConductorAgent().handle(_messages(("user", "hi")))

        assert response.content == "42"
        assert response.agent_name == CONDUCTOR_AGENT_NAME

    async def test_an_empty_answer_still_says_something(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A completed task with no text is a success, and an empty assistant
        message renders as nothing at all in a chat client."""
        monkeypatch.setattr(
            "maistro_server.conductor_agent.run_task",
            AsyncMock(return_value=ConductorOutput(final_answer="", success=True)),
        )

        response = await ConductorAgent().handle(_messages(("user", "hi")))

        assert response.content == "Task completed successfully."

    async def test_a_provider_failure_is_raised_not_answered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The endpoint above maps the exception *type* to 502 or 504, so the
        exception has to survive. Converting it into a normal-looking answer
        here would make an outage indistinguishable from a reply, and would
        cost the status code a client branches on."""
        monkeypatch.setattr(
            "maistro_server.conductor_agent.run_task",
            AsyncMock(side_effect=LLMProviderError("https://provider.internal key=sk-secret")),
        )

        with pytest.raises(LLMProviderError):
            await ConductorAgent().handle(_messages(("user", "hi")))


class TestTheTierIsNotTrusted:
    """`intent.tier` is not reliably an int at this seam.

    `determine_execution_tier` copies `agent.priority_tier` over it, and those
    are `"P0"`-style labels — so a classified turn could otherwise become a
    validation error, which is worse than the default tier every turn used
    before this existed.
    """

    def test_no_intent_means_no_tier(self) -> None:
        assert _tier_kwargs(None) == {}

    def test_a_numeric_tier_is_carried(self) -> None:
        assert _tier_kwargs(Intent(task_type="chat", tier=2)) == {"tier": 2}

    def test_a_label_tier_is_dropped(self) -> None:
        assert _tier_kwargs(Intent(task_type="chat", tier="P0")) == {}  # type: ignore[arg-type]

    def test_a_boolean_tier_is_dropped(self) -> None:
        """`True` is an `int` in Python, so an unguarded check would silently
        run the turn at tier 1."""

        class _Intent:
            tier = True

        assert _tier_kwargs(_Intent()) == {}


class TestTheAgentHasNoTierOpinion:
    def test_it_declares_no_priority_tier(self) -> None:
        """`determine_execution_tier` overrides the classifier's tier whenever
        the attribute *exists* — `hasattr`, not truthiness — so `None` would
        override just as firmly as a number. Absence is the only way to say
        "no opinion", and honouring the classification is the point."""
        assert not hasattr(ConductorAgent(), "priority_tier")


class TestLastUserMessage:
    def test_it_skips_non_user_roles(self) -> None:
        assert _last_user_message(_messages(("user", "a"), ("assistant", "b"))) == "a"

    def test_it_skips_an_empty_user_message(self) -> None:
        """An empty string is not a question. Taking it would hand `run_task` a
        blank description while a real one sat one message earlier."""
        assert _last_user_message(_messages(("user", "a"), ("user", ""))) == "a"

    def test_a_non_string_content_is_not_a_message(self) -> None:
        """The OpenAI schema allows content parts as a list. This seam takes
        text, and guessing at a structure it does not understand would send
        something arbitrary to the conductor."""
        assert _last_user_message([{"role": "user", "content": [{"type": "text"}]}]) == ""
