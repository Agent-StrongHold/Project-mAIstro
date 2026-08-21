from __future__ import annotations

import json

import pytest

from maistro.graph.run import GraphRun
from maistro.graph.types import (
    AgentRole,
    GraphConfig,
    GraphEdge,
    GraphTask,
    PlanOutput,
)
from maistro.testing.faux_provider import (
    FauxProvider,
    FauxResponse,
    ToolCallDef,
    code_output,
    plan_output,
    review_output,
    scout_output,
)

# NOTE: tests drive coroutines with native `async def` + `await`, run by
# pytest-asyncio (auto mode). Do NOT use asyncio.get_event_loop().run_until_
# complete(): under auto mode the loop state left by earlier async tests makes
# get_event_loop() raise, producing order-dependent ("flaky") failures.


class TestFauxResponse:
    def test_defaults(self):
        fr = FauxResponse()
        assert fr.content == ""
        assert fr.tool_calls == []
        assert fr.finish_reason == "stop"
        assert fr.error is None

    def test_tool_call_response(self):
        fr = FauxResponse(
            content="",
            tool_calls=[ToolCallDef(name="read_file", arguments={"path": "/tmp/x"})],
            finish_reason="tool_calls",
        )
        assert len(fr.tool_calls) == 1
        assert fr.tool_calls[0].name == "read_file"

    def test_error_response(self):
        exc = RuntimeError("test error")
        fr = FauxResponse(error=exc)
        assert fr.error is exc


class TestFauxProviderBasic:
    async def test_default_response_when_empty(self):
        provider = FauxProvider()
        result = await provider([{"role": "user", "content": "hello"}])
        assert "faux plan" in result

    async def test_seeded_response_returned(self):
        provider = FauxProvider()
        provider.seed(FauxResponse(content="hello world"))
        result = await provider([{"role": "user", "content": "hi"}])
        assert result == "hello world"

    async def test_sequenced_responses(self):
        provider = FauxProvider()
        provider.seed(
            FauxResponse(content="first"),
            FauxResponse(content="second"),
            FauxResponse(content="third"),
        )
        assert await provider([]) == "first"
        assert await provider([]) == "second"
        assert await provider([]) == "third"
        # Past the seeded list → default response.
        assert (await provider([])) == "first" or "faux plan" in (await provider([]))

    async def test_seed_json_with_dict(self):
        provider = FauxProvider()
        provider.seed_json({"summary": "test plan", "subtasks": []})
        result = await provider([])
        parsed = json.loads(result)
        assert parsed["summary"] == "test plan"

    async def test_seed_json_with_pydantic(self):
        provider = FauxProvider()
        provider.seed_json(PlanOutput(summary="pydantic plan"))
        result = await provider([])
        parsed = json.loads(result)
        assert parsed["summary"] == "pydantic plan"

    async def test_seed_error(self):
        provider = FauxProvider()
        provider.seed_error(ConnectionError("network down"))
        with pytest.raises(ConnectionError, match="network down"):
            await provider([])

    async def test_seed_tool_call(self):
        provider = FauxProvider()
        provider.seed_tool_call("run_code", {"language": "python", "code": "print(1)"})
        result = await provider.complete([{"role": "user", "content": "run"}])
        choice = result["choices"][0]
        assert choice["finish_reason"] == "tool_calls"
        assert len(choice["message"]["tool_calls"]) == 1
        tc = choice["message"]["tool_calls"][0]
        assert tc["function"]["name"] == "run_code"

    async def test_call_log(self):
        provider = FauxProvider()
        msgs = [{"role": "user", "content": "hello"}]
        await provider(msgs, model="test-model")
        assert provider.call_count == 1
        assert provider.last_messages() == msgs
        entry = provider.last_call()
        assert entry["model"] == "test-model"

    async def test_reset(self):
        provider = FauxProvider()
        provider.seed(FauxResponse(content="x"))
        await provider([])
        assert provider.call_count == 1
        provider.reset()
        assert provider.call_count == 0
        assert provider._index == 0


class TestFauxProviderComplete:
    async def test_returns_openai_format(self):
        provider = FauxProvider()
        provider.seed(
            FauxResponse(
                content="test response",
                usage_prompt_tokens=50,
                usage_completion_tokens=25,
                model="faux://test-model",
            )
        )
        result = await provider.complete([{"role": "user", "content": "hi"}])
        assert result["object"] == "chat.completion"
        assert result["model"] == "faux://test-model"
        assert result["choices"][0]["message"]["content"] == "test response"
        assert result["choices"][0]["finish_reason"] == "stop"
        assert result["usage"]["prompt_tokens"] == 50
        assert result["usage"]["completion_tokens"] == 25
        assert result["usage"]["total_tokens"] == 75

    async def test_tool_calls_in_response(self):
        provider = FauxProvider()
        provider.seed(
            FauxResponse(
                content="",
                tool_calls=[
                    ToolCallDef(name="func_a", arguments={"x": 1}, call_id="call_0"),
                    ToolCallDef(name="func_b", arguments={"y": 2}),
                ],
                finish_reason="tool_calls",
            )
        )
        result = await provider.complete([{"role": "user", "content": "go"}])
        tcs = result["choices"][0]["message"]["tool_calls"]
        assert len(tcs) == 2
        assert tcs[0]["id"] == "call_0"
        assert tcs[0]["function"]["name"] == "func_a"
        assert json.loads(tcs[0]["function"]["arguments"]) == {"x": 1}

    async def test_metadata_logged(self):
        provider = FauxProvider()
        meta = {"trace_id": "abc123"}
        await provider.complete(
            [{"role": "user", "content": "hi"}],
            metadata=meta,
        )
        assert provider.last_call()["metadata"] == meta


class TestFauxProviderStream:
    async def test_stream_yields_sse_chunks(self):
        provider = FauxProvider()
        provider.seed(FauxResponse(content="hello world"))

        chunks = [chunk async for chunk in provider.stream([{"role": "user", "content": "hi"}])]
        assert len(chunks) >= 3
        data_chunks = [c for c in chunks if c.startswith("data: {")]
        reassembled = ""
        for dc in data_chunks:
            obj = json.loads(dc.removeprefix("data: ").removesuffix("\n\n"))
            delta = obj["choices"][0].get("delta", {})
            reassembled += delta.get("content", "")
        assert reassembled == "hello world"
        assert chunks[-1] == "data: [DONE]\n\n"

    async def test_stream_error_propagates(self):
        provider = FauxProvider()
        provider.seed_error(ValueError("stream broke"))

        with pytest.raises(ValueError, match="stream broke"):
            async for _chunk in provider.stream([{"role": "user", "content": "hi"}]):
                pass


class TestFauxProviderCallable:
    async def test_callable_returns_string(self):
        provider = FauxProvider()
        provider.seed(FauxResponse(content="direct call"))
        result = await provider([{"role": "user", "content": "test"}])
        assert result == "direct call"

    async def test_callable_logs_call(self):
        provider = FauxProvider()
        await provider([])
        assert provider.call_count == 1


class TestFauxProviderResponseSchema:
    """Regression: the graph node calls llm_call(..., response_schema=...).
    The FauxProvider must accept (and record) that forward-compatible kwarg
    rather than TypeError — otherwise every graph node fails deterministically
    in the harness."""

    async def test_complete_accepts_response_schema(self):
        provider = FauxProvider()
        provider.seed(FauxResponse(content="ok"))
        result = await provider.complete(
            [{"role": "user", "content": "hi"}],
            temperature=0.0,
            response_schema={"type": "object"},
        )
        assert result["choices"][0]["message"]["content"] == "ok"
        assert provider.last_call()["extra"]["response_schema"] == {"type": "object"}

    async def test_callable_accepts_response_schema(self):
        provider = FauxProvider()
        provider.seed(FauxResponse(content="ok"))
        result = await provider(
            [{"role": "user", "content": "hi"}],
            model="m",
            temperature=0.0,
            response_schema={"type": "object"},
        )
        assert result == "ok"


class TestHelperFactories:
    def test_plan_output_factory(self):
        fr = plan_output(summary="my plan", estimated_files=["a.py", "b.py"])
        parsed = json.loads(fr.content)
        assert parsed["summary"] == "my plan"
        assert parsed["estimated_files"] == ["a.py", "b.py"]

    def test_code_output_factory(self):
        fr = code_output(files_changed=["x.py"], description="did stuff", tests_added=True)
        parsed = json.loads(fr.content)
        assert parsed["files_changed"] == ["x.py"]
        assert parsed["tests_added"] is True

    def test_review_output_factory(self):
        fr = review_output(approved=True, score=9.5, issues=["minor typo"])
        parsed = json.loads(fr.content)
        assert parsed["approved"] is True
        assert parsed["score"] == 9.5
        assert parsed["issues"] == ["minor typo"]

    def test_scout_output_factory(self):
        fr = scout_output(relevant_files=["a.py", "b.py"], patterns="MVC")
        parsed = json.loads(fr.content)
        assert parsed["relevant_files"] == ["a.py", "b.py"]
        assert parsed["patterns"] == "MVC"


class TestFauxProviderWithGraphExecutor:
    async def test_full_pipeline_deterministic(self):
        provider = FauxProvider()
        provider.seed(
            plan_output(
                summary="test plan",
                subtasks=[
                    {"title": "do thing", "description": "implement it", "file_paths": ["main.py"]},
                ],
            ),
            code_output(files_changed=["main.py"], description="implemented"),
            review_output(approved=True, score=9.0),
        )

        task = GraphTask(description="Write a hello world function", workspace="/tmp")
        config = GraphConfig(
            nodes=[AgentRole.PLANNER, AgentRole.CODER, AgentRole.REVIEWER],
            edges=[
                GraphEdge(from_role=AgentRole.PLANNER, to_role=AgentRole.CODER),
                GraphEdge(from_role=AgentRole.CODER, to_role=AgentRole.REVIEWER),
            ],
            entry=AgentRole.PLANNER,
        )
        graph_run = GraphRun(task=task, config=config)

        result = await graph_run.start(provider, model="faux://test-model")

        assert result.success is True
        assert result.plan is not None
        assert result.plan.summary == "test plan"
        assert result.code is not None
        assert "main.py" in result.code.files_changed
        assert result.review is not None
        assert result.review.approved is True
        assert result.review.score == 9.0
        assert provider.call_count == 3

    async def test_pipeline_with_failure(self):
        provider = FauxProvider()
        provider.seed(
            plan_output(summary="failing plan"),
            FauxResponse(error=RuntimeError("LLM overloaded")),
        )

        task = GraphTask(description="test task", workspace="/tmp")
        config = GraphConfig(
            nodes=[AgentRole.PLANNER, AgentRole.CODER],
            entry=AgentRole.PLANNER,
        )
        graph_run = GraphRun(task=task, config=config)

        result = await graph_run.start(provider, model="faux://test-model", max_retries=0)

        assert result.success is False

    async def test_pipeline_with_scout(self):
        provider = FauxProvider()
        provider.seed(
            scout_output(relevant_files=["app.py"], summary="found files"),
            plan_output(summary="planned"),
            code_output(),
            review_output(approved=True),
        )

        task = GraphTask(description="refactor app", workspace="/src")
        config = GraphConfig(
            nodes=[AgentRole.PLANNER, AgentRole.CODER, AgentRole.REVIEWER],
            edges=[
                GraphEdge(from_role=AgentRole.PLANNER, to_role=AgentRole.CODER),
                GraphEdge(from_role=AgentRole.CODER, to_role=AgentRole.REVIEWER),
            ],
            entry=AgentRole.PLANNER,
            run_scout=True,
        )
        graph_run = GraphRun(task=task, config=config)

        result = await graph_run.start(provider, model="faux://test-model")

        assert result.success is True
        assert result.blackboard is not None
        assert result.blackboard.scout_context is not None
        assert "app.py" in result.blackboard.scout_context.relevant_files
        assert provider.call_count == 4

    async def test_messages_captured_per_node(self):
        provider = FauxProvider()
        provider.seed(
            plan_output(summary="test"),
            review_output(approved=True),
        )

        task = GraphTask(description="test", workspace="/tmp")
        config = GraphConfig(
            nodes=[AgentRole.PLANNER, AgentRole.REVIEWER],
            edges=[
                GraphEdge(from_role=AgentRole.PLANNER, to_role=AgentRole.REVIEWER),
            ],
            entry=AgentRole.PLANNER,
        )
        graph_run = GraphRun(task=task, config=config)
        await graph_run.start(provider, model="faux://test-model")

        assert provider.call_count == 2
        planner_msgs = provider.call_log[0]["messages"]
        assert any("planner" in m.get("content", "").lower() for m in planner_msgs)


class TestFauxProviderProtocolConformance:
    def test_implements_llm_client_protocol(self):
        from maistro.protocols.llm import LLMClient

        provider = FauxProvider()
        assert isinstance(provider, LLMClient)

    async def test_works_as_llm_call_callable(self):
        provider = FauxProvider()
        provider.seed_json({"summary": "callable test", "subtasks": [], "estimated_files": []})

        result = await provider(
            [{"role": "user", "content": "test"}],
            model="faux://test-model",
        )
        assert isinstance(result, str)
        parsed = json.loads(result)
        assert parsed["summary"] == "callable test"


class TestFauxProviderEdgeCases:
    async def test_empty_content(self):
        provider = FauxProvider()
        provider.seed(FauxResponse(content=""))
        result = await provider([])
        assert result == ""

    async def test_very_long_content(self):
        provider = FauxProvider()
        long_content = "x" * 100_000
        provider.seed(FauxResponse(content=long_content))
        result = await provider([])
        assert result == long_content

    async def test_unicode_content(self):
        provider = FauxProvider()
        provider.seed(FauxResponse(content="Hello, world! Bonjour! Hola!"))
        result = await provider([])
        assert "Bonjour" in result

    async def test_sequential_errors_then_success(self):
        provider = FauxProvider()
        provider.seed_error(TimeoutError("timeout"))
        provider.seed_error(ConnectionError("reset"))
        provider.seed(FauxResponse(content="finally works"))

        with pytest.raises(TimeoutError):
            await provider([])
        with pytest.raises(ConnectionError):
            await provider([])
        result = await provider([])
        assert result == "finally works"

    async def test_multiple_resets(self):
        provider = FauxProvider()
        provider.seed(FauxResponse(content="a"), FauxResponse(content="b"))
        assert await provider([]) == "a"
        provider.reset()
        assert await provider([]) == "a"
        assert await provider([]) == "b"
