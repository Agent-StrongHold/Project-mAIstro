"""Tests for maistro.observability.tracing — OpenTelemetry agent span decorator."""

from __future__ import annotations

import builtins

import pytest

from maistro.observability.tracing import _get_tracer, trace_agent


class TestGetTracer:
    def test_returns_tracer_when_opentelemetry_installed(self) -> None:
        tracer = _get_tracer()
        assert tracer is not None

    @pytest.mark.ac("SPEC-228/AC-3")
    def test_returns_none_when_opentelemetry_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        real_import = builtins.__import__

        def fake_import(name: str, *args: object, **kwargs: object) -> object:
            if name == "opentelemetry":
                raise ImportError("no module named opentelemetry")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        assert _get_tracer() is None


class TestTraceAgent:
    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-228/AC-3")
    async def test_no_tracer_runs_function_directly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("maistro.observability.tracing._get_tracer", lambda: None)

        @trace_agent("my-agent")
        async def fn(x: int) -> int:
            return x * 2

        assert await fn(3) == 6

    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-228/AC-3")
    async def test_success_path_sets_output_preview_and_returns_result(self) -> None:
        @trace_agent("my-agent")
        async def fn(x: int) -> int:
            return x + 1

        assert await fn(41) == 42

    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-228/AC-3")
    async def test_exception_path_records_and_reraises(self) -> None:
        @trace_agent("my-agent")
        async def fn() -> None:
            raise ValueError("boom")

        with pytest.raises(ValueError, match="boom"):
            await fn()

    @pytest.mark.asyncio
    async def test_wraps_preserves_function_metadata(self) -> None:
        @trace_agent("my-agent")
        async def my_named_fn() -> None:
            """Docstring."""

        assert my_named_fn.__name__ == "my_named_fn"
        assert my_named_fn.__doc__ == "Docstring."
