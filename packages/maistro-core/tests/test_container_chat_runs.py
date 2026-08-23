"""route_request() admits and closes a canonical Run (#131).

The chat half of #41. A turn now enters the same spine a task does: admitted as
a Run, moved to running, terminalized whichever way the turn ends, and reported
back additively as `run_id`. These go through `create_container()` specifically,
because the wiring is the thing being tested -- constructing a `ChatRunAdmitter`
directly proves nothing about whether the container reaches for it.
"""

from __future__ import annotations

import pytest

from maistro.container import Container, create_container
from maistro.runs.admission import ADMISSION_SOURCE
from maistro.runs.chat_admission import CHAT_SOURCE, SESSION_ID_KEY
from maistro.runs.model import TERMINAL_RUN_STATUSES, RunStatus
from maistro.types.config import AgentConfig


async def _container() -> Container:
    return await create_container(AgentConfig(router_api_key="test-key"))


class _Conduit:
    """Stands in for the real Conduit, which needs agents this test has not."""

    def __init__(self, *, raises: Exception | None = None) -> None:
        self.calls: list[list[dict[str, str]]] = []
        self._raises = raises

    async def route_request(self, messages, **_kwargs):
        self.calls.append(messages)
        if self._raises is not None:
            raise self._raises
        return {"choices": [{"message": {"role": "assistant", "content": "hi"}}]}


async def test_a_turn_yields_a_run_id_that_resolves() -> None:
    container = await _container()
    container.conduit = _Conduit()

    result = await container.route_request(
        [{"role": "user", "content": "what broke?"}], session_id="sess-1"
    )

    run = await container.run_store.get_run(result["run_id"])
    assert run is not None
    assert run.provenance[ADMISSION_SOURCE] == CHAT_SOURCE
    assert run.provenance[SESSION_ID_KEY] == "sess-1"


async def test_the_openai_shape_is_untouched() -> None:
    container = await _container()
    container.conduit = _Conduit()

    result = await container.route_request([{"role": "user", "content": "hi"}])

    assert result["choices"][0]["message"]["content"] == "hi"
    # Additive, not replacing: a caller that only reads `choices` is unaffected.
    assert set(result) == {"choices", "run_id"}


async def test_the_run_is_completed_when_the_turn_ends() -> None:
    container = await _container()
    container.conduit = _Conduit()

    result = await container.route_request([{"role": "user", "content": "hi"}])

    run = await container.run_store.get_run(result["run_id"])
    assert run is not None
    assert run.status is RunStatus.COMPLETED


async def test_a_raising_turn_still_closes_its_run() -> None:
    """A Run left RUNNING is what recovery reads as a process that died."""
    container = await _container()
    container.conduit = _Conduit(raises=RuntimeError("upstream exploded"))

    with pytest.raises(RuntimeError, match="upstream exploded"):
        await container.route_request([{"role": "user", "content": "hi"}])

    runs = [run for run in _chat_runs(container) if run.provenance[ADMISSION_SOURCE] == CHAT_SOURCE]
    assert len(runs) == 1
    assert runs[0].status is RunStatus.FAILED
    assert runs[0].status in TERMINAL_RUN_STATUSES


async def test_the_turn_is_answered_even_when_admission_fails() -> None:
    """The chat path has no receipt to fall back on, so it must not refuse."""
    container = await _container()
    conduit = _Conduit()
    container.conduit = conduit

    class _Broken:
        async def admit(self, *_args, **_kwargs):
            raise RuntimeError("no project")

    container.chat_admitter = _Broken()  # type: ignore[assignment]

    result = await container.route_request([{"role": "user", "content": "hi"}])

    assert len(conduit.calls) == 1
    assert "run_id" not in result


async def test_no_chat_admitter_means_no_run_id_and_no_failure() -> None:
    container = await _container()
    conduit = _Conduit()
    container.conduit = conduit
    container.chat_admitter = None  # type: ignore[assignment]

    result = await container.route_request([{"role": "user", "content": "hi"}])

    assert len(conduit.calls) == 1
    assert "run_id" not in result


async def test_the_chat_admitter_is_wired_by_the_container() -> None:
    container = await _container()

    assert container.chat_admitter is not None
    assert container.chat_admitter.retained == 0


def _chat_runs(container: Container):
    """Every Run in the container's store. Private access on purpose: the point
    is to see the Run the caller was *not* handed, because the turn raised."""
    return list(container.run_store._runs.values())  # type: ignore[attr-defined]
