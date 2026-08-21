"""Tests for ArtificerStrategy: plan -> phase loop (code -> check -> fix -> commit)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest

from maistro.agents.artificer.strategy import ArtificerStrategy, _noop_status
from maistro.testing.faux_provider import FauxProvider, FauxResponse


class _FakeSpan:
    def __init__(self) -> None:
        self.inputs: list[Any] = []
        self.outputs: list[Any] = []

    def __enter__(self) -> _FakeSpan:
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def set_input(self, data: Any) -> _FakeSpan:
        self.inputs.append(data)
        return self

    def set_output(self, data: Any) -> _FakeSpan:
        self.outputs.append(data)
        return self

    def set_usage(self, **_kwargs: Any) -> _FakeSpan:
        return self


class _FakeTrace:
    def __init__(self) -> None:
        self.span_names: list[str] = []

    def span(self, name: str) -> _FakeSpan:
        self.span_names.append(name)
        return _FakeSpan()


@dataclass
class _WardenVerdict:
    clean: bool = True
    flags: tuple[str, ...] = ()


class _FakeWarden:
    def __init__(self, *, clean: bool = True, flags: tuple[str, ...] = ()) -> None:
        self._clean = clean
        self._flags = flags

    async def scan(self, _text: str, _surface: str) -> _WardenVerdict:
        return _WardenVerdict(clean=self._clean, flags=self._flags)


@dataclass
class _SentinelVerdict:
    allowed: bool = True
    repaired_data: dict[str, Any] | None = None


class _FakeSentinel:
    def __init__(
        self, *, allowed: bool = True, repaired_data: dict[str, Any] | None = None
    ) -> None:
        self._allowed = allowed
        self._repaired_data = repaired_data

    async def pre_call(
        self, _tool_name: str, _args: dict[str, Any], _auth: Any, _schema: dict[str, Any]
    ) -> _SentinelVerdict:
        return _SentinelVerdict(allowed=self._allowed, repaired_data=self._repaired_data)

    async def post_call(self, _tool_name: str, result: str, _auth: Any) -> str:
        return f"sanitized:{result}"


class _Auth:
    user_id = "u1"


async def _echo_executor(_name: str, args: dict[str, Any]) -> str:
    return f"ran with {args}"


def _tools_for(name: str) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": "test tool",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]


@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("maistro.agents.artificer.strategy.asyncio.sleep", _no_sleep)


class TestNoopStatus:
    @pytest.mark.asyncio
    async def test_returns_none(self) -> None:
        assert await _noop_status("x") is None


class TestReasonNoToolCalls:
    @pytest.mark.asyncio
    async def test_returns_done_with_plan_and_result(self) -> None:
        provider = FauxProvider()
        provider.seed(FauxResponse(content="the plan"))
        provider.seed(FauxResponse(content="final result"))
        strategy = ArtificerStrategy(max_phases=2)

        result = await strategy.reason([{"role": "user", "content": "build x"}], "m", provider)

        assert result.done is True
        assert "## Plan\nthe plan" in result.response
        assert "## Result\nfinal result" in result.response
        assert result.tool_history == []


class TestReasonWithTrace:
    @pytest.mark.asyncio
    async def test_records_plan_and_llm_call_spans(self) -> None:
        provider = FauxProvider()
        provider.seed(FauxResponse(content="planned"))
        provider.seed(FauxResponse(content="done"))
        strategy = ArtificerStrategy(max_phases=2)
        trace = _FakeTrace()

        result = await strategy.reason(
            [{"role": "user", "content": "x"}], "m", provider, trace=trace
        )

        assert result.done is True
        assert trace.span_names == ["artificer.plan", "llm_call_0"]


class TestReasonWithToolCalls:
    @pytest.mark.asyncio
    async def test_executes_tool_then_completes(self) -> None:
        provider = FauxProvider()
        provider.seed(FauxResponse(content="planned"))
        provider.seed_tool_call("write_file", {"path": "a.py"})
        provider.seed(FauxResponse(content="all done"))
        strategy = ArtificerStrategy(max_phases=2)
        tools = _tools_for("write_file")

        result = await strategy.reason(
            [{"role": "user", "content": "x"}],
            "m",
            provider,
            tools=tools,
            tool_executor=_echo_executor,
        )

        assert result.done is True
        assert "all done" in result.response
        assert len(result.tool_history) == 1
        assert result.tool_history[0]["tool_name"] == "write_file"
        assert "ran with" in result.tool_history[0]["result"]

    @pytest.mark.asyncio
    async def test_tool_calls_non_list_treated_as_empty(self) -> None:
        provider = FauxProvider(default_response=FauxResponse(content="planned then no tools"))
        strategy = ArtificerStrategy(max_phases=1)

        result = await strategy.reason([{"role": "user", "content": "x"}], "m", provider)

        assert result.done is True


class TestReasonMaxRoundsReached:
    @pytest.mark.asyncio
    async def test_returns_max_rounds_message(self) -> None:
        provider = FauxProvider()
        provider.seed(FauxResponse(content="planned"))
        for _ in range(10):
            provider.seed_tool_call("write_file", {"path": "a.py"})
        strategy = ArtificerStrategy(max_phases=1)
        tools = _tools_for("write_file")

        result = await strategy.reason(
            [{"role": "user", "content": "x"}],
            "m",
            provider,
            tools=tools,
            tool_executor=_echo_executor,
        )

        assert result.done is True
        assert "Max rounds reached" in result.response


class TestCallLlm:
    @pytest.mark.asyncio
    async def test_without_trace(self) -> None:
        provider = FauxProvider()
        provider.seed(FauxResponse(content="ok"))
        strategy = ArtificerStrategy()

        response = await strategy._call_llm(
            provider, [{"role": "user", "content": "x"}], "m", None, None, 0
        )

        assert response["choices"][0]["message"]["content"] == "ok"

    @pytest.mark.asyncio
    async def test_with_trace_records_usage(self) -> None:
        provider = FauxProvider()
        provider.seed(FauxResponse(content="ok", usage_prompt_tokens=3, usage_completion_tokens=4))
        strategy = ArtificerStrategy()
        trace = _FakeTrace()

        response = await strategy._call_llm(
            provider, [{"role": "user", "content": "x"}], "m", None, trace, 2
        )

        assert response["choices"][0]["message"]["content"] == "ok"
        assert trace.span_names == ["llm_call_2"]


class TestRunTool:
    @pytest.mark.asyncio
    async def test_no_executor_returns_unavailable_message(self) -> None:
        strategy = ArtificerStrategy()
        result = await strategy._run_tool("write_file", {}, None, None)
        assert result == "Tool 'write_file' not available"

    @pytest.mark.asyncio
    async def test_non_callable_executor_returns_unavailable_message(self) -> None:
        strategy = ArtificerStrategy()
        result = await strategy._run_tool("write_file", {}, "not-callable", None)
        assert result == "Tool 'write_file' not available"

    @pytest.mark.asyncio
    async def test_without_trace_invokes_executor(self) -> None:
        strategy = ArtificerStrategy()
        result = await strategy._run_tool("write_file", {"a": 1}, _echo_executor, None)
        assert result == "ran with {'a': 1}"

    @pytest.mark.asyncio
    async def test_with_trace_records_success_span(self) -> None:
        strategy = ArtificerStrategy()
        trace = _FakeTrace()

        async def _ok_executor(_name: str, _args: dict[str, Any]) -> str:
            return '{"passed": true}'

        result = await strategy._run_tool("run_pytest", {}, _ok_executor, trace)

        assert result == '{"passed": true}'
        assert trace.span_names == ["tool.run_pytest"]

    @pytest.mark.asyncio
    async def test_with_trace_records_failure_span(self) -> None:
        strategy = ArtificerStrategy()
        trace = _FakeTrace()

        async def _err_executor(_name: str, _args: dict[str, Any]) -> str:
            return "Error: something broke"

        result = await strategy._run_tool("run_pytest", {}, _err_executor, trace)

        assert result == "Error: something broke"
        assert trace.span_names == ["tool.run_pytest"]

    @pytest.mark.asyncio
    async def test_with_trace_status_ok_string(self) -> None:
        strategy = ArtificerStrategy()
        trace = _FakeTrace()

        async def _status_ok_executor(_name: str, _args: dict[str, Any]) -> str:
            return '{"status": "ok"}'

        result = await strategy._run_tool("run_mypy", {}, _status_ok_executor, trace)
        assert result == '{"status": "ok"}'


class TestSanitizeResult:
    @pytest.mark.asyncio
    async def test_sentinel_and_auth_present_uses_post_call(self) -> None:
        strategy = ArtificerStrategy()
        sentinel = _FakeSentinel()
        result = await strategy._sanitize_result(
            "write_file", "raw result", sentinel=sentinel, auth=_Auth(), warden=None
        )
        assert result == "sanitized:raw result"

    @pytest.mark.asyncio
    async def test_warden_clean_passthrough(self) -> None:
        strategy = ArtificerStrategy()
        warden = _FakeWarden(clean=True)
        result = await strategy._sanitize_result(
            "write_file", "raw result", sentinel=None, auth=None, warden=warden
        )
        assert result == "raw result"

    @pytest.mark.asyncio
    async def test_warden_dirty_blocks_result(self) -> None:
        strategy = ArtificerStrategy()
        warden = _FakeWarden(clean=False, flags=("injection",))
        result = await strategy._sanitize_result(
            "write_file", "raw result", sentinel=None, auth=None, warden=warden
        )
        assert "[BLOCKED" in result
        assert "injection" in result

    @pytest.mark.asyncio
    async def test_no_sentinel_no_warden_passthrough(self) -> None:
        strategy = ArtificerStrategy()
        result = await strategy._sanitize_result(
            "write_file", "raw result", sentinel=None, auth=None, warden=None
        )
        assert result == "raw result"


class TestEmitResultStatus:
    @pytest.mark.asyncio
    async def test_passed_true_emits_ok(self) -> None:
        strategy = ArtificerStrategy()
        seen: list[str] = []

        async def _status(msg: str) -> None:
            seen.append(msg)

        await strategy._emit_result_status("run_pytest", '{"passed": true}', _status)
        assert seen == ["run_pytest: OK"]

    @pytest.mark.asyncio
    async def test_status_ok_emits_ok(self) -> None:
        strategy = ArtificerStrategy()
        seen: list[str] = []

        async def _status(msg: str) -> None:
            seen.append(msg)

        await strategy._emit_result_status("run_mypy", '{"status": "ok"}', _status)
        assert seen == ["run_mypy: OK"]

    @pytest.mark.asyncio
    async def test_passed_false_emits_failed(self) -> None:
        strategy = ArtificerStrategy()
        seen: list[str] = []

        async def _status(msg: str) -> None:
            seen.append(msg)

        await strategy._emit_result_status("run_pytest", '{"passed": false}', _status)
        assert seen == ["run_pytest: FAILED -- fixing..."]

    @pytest.mark.asyncio
    async def test_error_and_failed_status_emits_retrying(self) -> None:
        strategy = ArtificerStrategy()
        seen: list[str] = []

        async def _status(msg: str) -> None:
            seen.append(msg)

        await strategy._emit_result_status(
            "run_pytest", '{"error": "x", "status": "failed"}', _status
        )
        assert seen == ["run_pytest: error -- retrying..."]

    @pytest.mark.asyncio
    async def test_no_match_emits_nothing(self) -> None:
        strategy = ArtificerStrategy()
        seen: list[str] = []

        async def _status(msg: str) -> None:
            seen.append(msg)

        await strategy._emit_result_status("run_pytest", "unrelated text", _status)
        assert seen == []


class TestHandleToolCall:
    @pytest.mark.asyncio
    async def test_success_path(self) -> None:
        strategy = ArtificerStrategy()
        tc = {
            "id": "call_1",
            "function": {"name": "write_file", "arguments": json.dumps({"path": "a.py"})},
        }
        seen: list[str] = []

        async def _status(msg: str) -> None:
            seen.append(msg)

        tool_args, result_str = await strategy._handle_tool_call(
            tc,
            tool_executor=_echo_executor,
            trace=None,
            status=_status,
            sentinel=None,
            auth=None,
            warden=None,
        )

        assert tool_args == {"path": "a.py"}
        assert "ran with" in result_str
        assert any("Running write_file" in s for s in seen)

    @pytest.mark.asyncio
    async def test_malformed_json_args_defaults_empty(self) -> None:
        strategy = ArtificerStrategy()
        tc = {"id": "call_1", "function": {"name": "write_file", "arguments": "not-json"}}

        tool_args, result_str = await strategy._handle_tool_call(
            tc,
            tool_executor=_echo_executor,
            trace=None,
            status=_noop_status,
            sentinel=None,
            auth=None,
            warden=None,
        )

        assert tool_args == {}
        assert "ran with" in result_str

    @pytest.mark.asyncio
    async def test_oversized_args_returns_error(self) -> None:
        strategy = ArtificerStrategy()
        big_value = "x" * 40_000
        tc = {
            "id": "call_1",
            "function": {
                "name": "write_file",
                "arguments": json.dumps({"content": big_value}),
            },
        }

        _tool_args, result_str = await strategy._handle_tool_call(
            tc,
            tool_executor=_echo_executor,
            trace=None,
            status=_noop_status,
            sentinel=None,
            auth=None,
            warden=None,
        )

        assert "exceed" in result_str

    @pytest.mark.asyncio
    async def test_sentinel_denies_blocks_call(self) -> None:
        strategy = ArtificerStrategy()
        sentinel = _FakeSentinel(allowed=False)
        tc = {"id": "call_1", "function": {"name": "write_file", "arguments": "{}"}}

        _tool_args, result_str = await strategy._handle_tool_call(
            tc,
            tool_executor=_echo_executor,
            trace=None,
            status=_noop_status,
            sentinel=sentinel,
            auth=_Auth(),
            warden=None,
        )

        assert "Permission denied" in result_str

    @pytest.mark.asyncio
    async def test_sentinel_repairs_args(self) -> None:
        strategy = ArtificerStrategy()
        sentinel = _FakeSentinel(allowed=True, repaired_data={"path": "repaired.py"})
        tc = {
            "id": "call_1",
            "function": {"name": "write_file", "arguments": json.dumps({"path": "a.py"})},
        }

        tool_args, result_str = await strategy._handle_tool_call(
            tc,
            tool_executor=_echo_executor,
            trace=None,
            status=_noop_status,
            sentinel=sentinel,
            auth=_Auth(),
            warden=None,
        )

        assert tool_args == {"path": "repaired.py"}
        assert "repaired.py" in result_str

    @pytest.mark.asyncio
    async def test_long_result_truncated(self) -> None:
        strategy = ArtificerStrategy()

        async def _big_executor(_name: str, _args: dict[str, Any]) -> str:
            return "y" * 20_000

        tc = {"id": "call_1", "function": {"name": "write_file", "arguments": "{}"}}

        _tool_args, result_str = await strategy._handle_tool_call(
            tc,
            tool_executor=_big_executor,
            trace=None,
            status=_noop_status,
            sentinel=None,
            auth=None,
            warden=None,
        )

        assert "[... truncated" in result_str


class TestPlan:
    @pytest.mark.asyncio
    async def test_returns_plan_content(self) -> None:
        provider = FauxProvider()
        provider.seed(FauxResponse(content="the plan body"))
        strategy = ArtificerStrategy()

        plan = await strategy._plan([{"role": "user", "content": "x"}], "m", provider)

        assert plan == "the plan body"

    @pytest.mark.asyncio
    async def test_no_choices_returns_default(self) -> None:
        class _EmptyChoicesProvider:
            async def complete(
                self, _messages: list[dict[str, Any]], _model: str, **_kwargs: Any
            ) -> dict[str, Any]:
                return {"choices": []}

        strategy = ArtificerStrategy()
        plan = await strategy._plan(
            [{"role": "user", "content": "x"}], "m", _EmptyChoicesProvider()
        )

        assert plan == "No plan generated"
