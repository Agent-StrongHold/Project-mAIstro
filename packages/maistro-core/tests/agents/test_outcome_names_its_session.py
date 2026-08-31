"""An outcome names its session as a session, and the ledger is charged per turn (#748).

`agents/base.py` is the only production site that writes `Outcome.request_id`,
and it wrote the session id there -- because `Outcome` had no session field to
write it to, beside the three canonical columns #709 added that do mean what
they say. It passed the same value to `charge_usage(request_id=)`, which makes
every turn of one conversation share a billing key.

These drive the real `Agent.handle` against doubles for the two collaborators
that matter, for the reason `test_base.py` drives it the same way: what is
under test is the values the agent hands each collaborator, and a server would
not make those any more visible.
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro.agents.base import Agent
from maistro.observability.correlation import bind_execution_context
from maistro.types.agent import AgentIdentity, ReasoningResult

pytestmark = [pytest.mark.contract("behavioral")]


class _Verdict:
    clean = True
    flags: tuple[str, ...] = ()


class _Warden:
    async def scan(self, text: str, _surface: str) -> _Verdict:
        del text
        return _Verdict()


class _ContextBuilder:
    async def build(
        self, messages: list[dict[str, Any]], _identity: Any, **_kwargs: Any
    ) -> tuple[list[dict[str, Any]], list[int]]:
        return messages, []


class _PromptManager:
    async def get(self, _name: str) -> str:
        return ""


class _Strategy:
    async def reason(self, *_args: Any, **_kwargs: Any) -> ReasoningResult:
        return ReasoningResult(response="done", input_tokens=10, output_tokens=20)


class _OutcomeStore:
    def __init__(self) -> None:
        self.recorded: list[Any] = []

    async def record(self, outcome: Any) -> None:
        self.recorded.append(outcome)


class _Ledger:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def charge_usage(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"charged_microchips": 5, "pricing_version": "v1"}


class _Auth:
    user_id = "u1"
    org_id = "org-1"
    team_id = "team-1"


def _agent(outcomes: _OutcomeStore, ledger: _Ledger | None = None) -> Agent:
    return Agent(
        identity=AgentIdentity(name="tester", model="test-model"),
        strategy=_Strategy(),
        llm=object(),
        context_builder=_ContextBuilder(),
        prompt_manager=_PromptManager(),
        warden=_Warden(),
        outcome_store=outcomes,
        coin_ledger=ledger,
    )


async def _turn(agent: Agent, session_id: str | None) -> None:
    await agent.handle(
        messages=[{"role": "user", "content": "hello"}], auth=_Auth(), session_id=session_id
    )


class TestAnOutcomeNamesItsSession:
    @pytest.mark.ac("SPEC-083026-56ee/AC-4")
    async def test_the_session_lands_in_the_session_field(self) -> None:
        outcomes = _OutcomeStore()
        await _turn(_agent(outcomes), "sess-1")

        assert outcomes.recorded[0].session_id == "sess-1"

    @pytest.mark.ac("SPEC-083026-56ee/AC-4")
    async def test_the_request_field_never_holds_the_session(self) -> None:
        """The whole defect: a column named for one canonical id, carrying
        another. `ExecutionContext` distinguishes them, so the record must."""
        outcomes = _OutcomeStore()
        await _turn(_agent(outcomes), "sess-1")

        assert outcomes.recorded[0].request_id != "sess-1"

    @pytest.mark.ac("SPEC-083026-56ee/AC-4")
    async def test_the_request_field_holds_the_request_when_one_is_in_scope(self) -> None:
        outcomes = _OutcomeStore()
        with bind_execution_context(request_id="req-9", session_id="ignored"):
            await _turn(_agent(outcomes), "sess-1")

        recorded = outcomes.recorded[0]
        assert recorded.request_id == "req-9"
        assert recorded.session_id == "sess-1"

    @pytest.mark.ac("SPEC-083026-56ee/AC-4")
    async def test_a_turn_outside_a_session_names_none(self) -> None:
        """Not the empty-string session that `session_id or ""` used to make
        indistinguishable from a session whose id happens to be blank."""
        outcomes = _OutcomeStore()
        await _turn(_agent(outcomes), None)

        recorded = outcomes.recorded[0]
        assert recorded.session_id == ""
        assert recorded.request_id == ""


class TestTheLedgerIsChargedPerTurn:
    @pytest.mark.ac("SPEC-083026-56ee/AC-5")
    async def test_two_turns_of_one_session_are_charged_under_different_keys(self) -> None:
        """The reason this is a correction and not a cleanup: a ledger that
        dedupes on the key drops the second charge outright."""
        ledger = _Ledger()
        agent = _agent(_OutcomeStore(), ledger)
        for run_id in ("run-1", "run-2"):
            with bind_execution_context(run_id=run_id):
                await _turn(agent, "sess-1")

        keys = [call["request_id"] for call in ledger.calls]
        assert keys == ["run-1", "run-2"]

    @pytest.mark.ac("SPEC-083026-56ee/AC-5")
    async def test_the_key_names_the_turns_own_execution(self) -> None:
        ledger = _Ledger()
        with bind_execution_context(run_id="run-1", attempt_id="a-1"):
            await _turn(_agent(_OutcomeStore(), ledger), "sess-1")

        assert ledger.calls[0]["request_id"] == "run-1"

    @pytest.mark.ac("SPEC-083026-56ee/AC-5")
    async def test_the_session_is_never_the_key(self) -> None:
        ledger = _Ledger()
        with bind_execution_context(run_id="run-1"):
            await _turn(_agent(_OutcomeStore(), ledger), "sess-1")

        assert ledger.calls[0]["request_id"] != "sess-1"

    @pytest.mark.ac("SPEC-083026-56ee/AC-5")
    async def test_a_turn_with_no_run_falls_back_to_the_request(self) -> None:
        """A container with no chat admitter binds no Run. The request id is
        the next-narrowest thing that is still per-turn; the session, which is
        what was passed before, is not per-turn at all."""
        ledger = _Ledger()
        with bind_execution_context(request_id="req-9"):
            await _turn(_agent(_OutcomeStore(), ledger), "sess-1")

        assert ledger.calls[0]["request_id"] == "req-9"
