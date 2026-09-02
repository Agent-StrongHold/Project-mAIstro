"""Tests for maistro.observability.tracing — OpenTelemetry agent span decorator."""

from __future__ import annotations

import builtins
import runpy
from pathlib import Path
from types import TracebackType
from typing import Any, cast

import pytest

from maistro.observability import telemetry_safety, tracing
from maistro.observability.correlation import bind_execution_context
from maistro.observability.tracing import _get_tracer, trace_agent

_CREDENTIAL_PARTS = (
    "sk-",
    "test_ABCDE",
    "FGHIJKLMNO",
    "PQRSTUVWXY",
    "Z123456",
)
SECRET = "".join(_CREDENTIAL_PARTS)


@pytest.fixture(autouse=True)
def _fresh_failure_reports(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(telemetry_safety, "_REPORTED_FAILURE_CATEGORIES", set())


class _RecordingSpan:
    def __init__(self, *, writes_raise: bool = False) -> None:
        self.attributes: dict[str, object] = {}
        self.statuses: list[object] = []
        self.recorded_exceptions: list[BaseException] = []
        self._writes_raise = writes_raise

    def set_attribute(self, key: str, value: object) -> None:
        if self._writes_raise:
            raise RuntimeError("span attribute writer failed")
        self.attributes[key] = value

    def set_status(self, status: object, description: str | None = None) -> None:
        if self._writes_raise:
            raise RuntimeError("span status writer failed")
        self.statuses.append((status, description))

    def record_exception(self, exc: BaseException) -> None:
        self.recorded_exceptions.append(exc)


class _SpanManager:
    def __init__(self, span: _RecordingSpan, *, exit_raises: bool = False) -> None:
        self.span = span
        self.exit_args: list[
            tuple[type[BaseException] | None, BaseException | None, TracebackType | None]
        ] = []
        self._exit_raises = exit_raises

    def __enter__(self) -> _RecordingSpan:
        return self.span

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.exit_args.append((exc_type, exc_value, traceback))
        if self._exit_raises:
            raise RuntimeError("span exporter failed")


class _RecordingTracer:
    def __init__(
        self,
        span: _RecordingSpan | None = None,
        *,
        start_raises: bool = False,
        exit_raises: bool = False,
    ) -> None:
        self.span = span or _RecordingSpan()
        self.manager = _SpanManager(self.span, exit_raises=exit_raises)
        self.started: list[tuple[str, bool, bool]] = []
        self._start_raises = start_raises

    def start_as_current_span(
        self,
        name: str,
        *,
        record_exception: bool = True,
        set_status_on_exception: bool = True,
    ) -> _SpanManager:
        if self._start_raises:
            raise RuntimeError("tracer failed to start")
        self.started.append((name, record_exception, set_status_on_exception))
        return self.manager


class TestTelemetrySafetyPolicy:
    def test_labels_fail_closed_and_cardinality_fallback_is_fixed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        assert telemetry_safety.sanitize_telemetry_label(object()) == "redacted"
        assert telemetry_safety.sanitize_telemetry_label("") == "redacted"
        assert telemetry_safety.sanitize_telemetry_label("x" * 129) == "redacted"
        assert telemetry_safety.sanitize_telemetry_label(SECRET) == "redacted"
        assert telemetry_safety.sanitize_telemetry_label("free form payload") == "redacted"
        assert (
            telemetry_safety.allowlisted_telemetry_label(
                "not-configured",
                tuple(f"configured-{index}" for index in range(129)),
                fallback="attacker-selected-fallback",
            )
            == "other"
        )

        def broken_scan(_value: str) -> list[str]:
            raise RuntimeError("detector unavailable")

        monkeypatch.setattr(telemetry_safety._PII_DETECTOR, "scan", broken_scan)
        assert telemetry_safety.sanitize_telemetry_label("otherwise-valid") == "redacted"

    def test_generic_attribute_writer_rejects_unapproved_strings_and_ranges(self) -> None:
        span = _RecordingSpan()

        telemetry_safety.set_span_attributes(
            span,
            {
                "arbitrary.key": "payload",
                "error.type": "attacker_error",
                "fantasia.streaming": True,
                "fantasia.user.present": "yes",
                "fantasia.iteration": 2,
                "fantasia.retry_count": 11,
                "gen_ai.usage.total_tokens": -1,
            },
        )
        telemetry_safety.set_allowlisted_span_attribute(
            span,
            "arbitrary.key",
            "value",
            {"value"},
            fallback="other",
        )

        assert span.attributes == {
            "fantasia.streaming": True,
            "fantasia.iteration": 2,
        }

    def test_failure_reporting_is_once_only_and_itself_fail_open(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        telemetry_safety.report_telemetry_failure("unknown", RuntimeError)
        telemetry_safety.report_telemetry_failure("tracer_lookup", RuntimeError)
        telemetry_safety.report_telemetry_failure("tracer_lookup", ValueError)

        monkeypatch.setattr(
            telemetry_safety.logger,
            "warning",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("logger failed")),
        )
        telemetry_safety.report_telemetry_failure("span_close", RuntimeError)

    def test_custom_reporter_failure_and_missing_status_code_are_fail_open(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        span = _RecordingSpan(writes_raise=True)

        def broken_reporter(_category: str, _error_type: type[BaseException]) -> None:
            raise RuntimeError("reporter failed")

        telemetry_safety.set_span_attributes(
            span,
            {"gen_ai.system": "litellm"},
            reporter=broken_reporter,
        )
        monkeypatch.setattr(telemetry_safety, "_STATUS_CODE_ERROR", None)
        telemetry_safety.mark_span_error(span)

    def test_exception_type_names_are_finite(self) -> None:
        class CustomControlFlow(BaseException):
            pass

        assert telemetry_safety.safe_exception_type_name(CustomControlFlow) == "Exception"
        assert telemetry_safety.safe_exception_type_name(cast(Any, object())) == "Exception"


class TestGetTracer:
    def test_returns_tracer_when_opentelemetry_installed(self) -> None:
        tracer = _get_tracer()
        assert tracer is not None

    @pytest.mark.ac("SPEC-228/AC-3")
    def test_returns_none_when_opentelemetry_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(tracing, "_otel_trace", None)
        assert _get_tracer() is None

    def test_lookup_failure_is_reported_safely_and_returns_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        class _BrokenTraceAPI:
            @staticmethod
            def get_tracer(_name: str) -> object:
                raise RuntimeError(f"lookup details {SECRET}")

        monkeypatch.setattr(tracing, "_otel_trace", _BrokenTraceAPI())
        with caplog.at_level("WARNING", logger="maistro.telemetry"):
            assert _get_tracer() is None

        assert "error_type=RuntimeError" in caplog.text
        assert SECRET not in caplog.text

    @pytest.mark.parametrize(
        ("module_path", "missing_name"),
        [
            (Path(tracing.__file__), "_otel_trace"),
            (Path(telemetry_safety.__file__), "_STATUS_CODE_ERROR"),
        ],
    )
    def test_runtime_optional_import_failure_is_fail_open(
        self,
        monkeypatch: pytest.MonkeyPatch,
        module_path: Path,
        missing_name: str,
    ) -> None:
        real_import = builtins.__import__

        def skewed_import(name: str, *args: object, **kwargs: object) -> object:
            if name.startswith("opentelemetry"):
                raise RuntimeError(f"version skew {SECRET}")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", skewed_import)
        namespace = runpy.run_path(str(module_path))

        assert namespace[missing_name] is None

    @pytest.mark.parametrize(
        "module_path",
        [Path(tracing.__file__), Path(telemetry_safety.__file__)],
    )
    def test_optional_import_does_not_swallow_base_exception(
        self,
        monkeypatch: pytest.MonkeyPatch,
        module_path: Path,
    ) -> None:
        class ImportAborted(BaseException):
            pass

        real_import = builtins.__import__

        def aborted_import(name: str, *args: object, **kwargs: object) -> object:
            if name.startswith("opentelemetry"):
                raise ImportAborted
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", aborted_import)
        with pytest.raises(ImportAborted):
            runpy.run_path(str(module_path))


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
    async def test_success_exports_no_ambient_ids_and_returns_exact_result(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tracer = _RecordingTracer()
        monkeypatch.setattr(tracing, "_get_tracer", lambda: tracer)
        result = object()

        @trace_agent("my-agent")
        async def fn() -> object:
            return result

        with bind_execution_context(run_id="run-123", request_id="request-456"):
            assert await fn() is result

        # The ContextVar does not carry provenance. In particular request_id
        # may come from X-Request-ID, so ambient values remain local.
        assert tracer.span.attributes == {}
        assert tracer.started == [("agent.call", False, False)]
        assert tracer.manager.exit_args == [(None, None, None)]
        assert "output" not in str(tracer.span.attributes).lower()

    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-228/AC-3")
    async def test_exception_content_and_stack_are_not_exported(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tracer = _RecordingTracer()
        monkeypatch.setattr(tracing, "_get_tracer", lambda: tracer)
        original = ValueError(f"raw failure {SECRET}")

        @trace_agent("my-agent")
        async def fn() -> None:
            stack_only_value = "stack-only-private-value"
            assert stack_only_value
            raise original

        with pytest.raises(ValueError) as exc_info:
            await fn()

        assert exc_info.value is original
        exported = repr((tracer.span.attributes, tracer.span.statuses, tracer.manager.exit_args))
        assert SECRET not in exported
        assert "stack-only-private-value" not in exported
        assert "raw failure" not in exported
        assert tracer.span.recorded_exceptions == []
        assert tracer.span.attributes["error.type"] == "application_error"
        assert tracer.manager.exit_args == [(None, None, None)]

    @pytest.mark.asyncio
    async def test_broken_tracer_does_not_change_successful_result(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tracer = _RecordingTracer(start_raises=True)
        monkeypatch.setattr(tracing, "_get_tracer", lambda: tracer)

        @trace_agent("my-agent")
        async def fn() -> int:
            return 42

        assert await fn() == 42

    @pytest.mark.asyncio
    async def test_broken_tracer_lookup_does_not_change_successful_result(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def broken_lookup() -> None:
            raise RuntimeError("tracer lookup failed")

        monkeypatch.setattr(tracing, "_get_tracer", broken_lookup)

        @trace_agent("my-agent")
        async def fn() -> int:
            return 42

        assert await fn() == 42

    @pytest.mark.asyncio
    async def test_broken_span_writes_and_exporter_do_not_change_successful_result(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        tracer = _RecordingTracer(_RecordingSpan(writes_raise=True), exit_raises=True)
        monkeypatch.setattr(tracing, "_get_tracer", lambda: tracer)

        @trace_agent("my-agent")
        async def fn() -> str:
            return "success"

        with (
            caplog.at_level("WARNING", logger="maistro.telemetry"),
            bind_execution_context(run_id="run-123"),
        ):
            assert await fn() == "success"

        assert caplog.text.count("span close failed") == 1
        assert "error_type=RuntimeError" in caplog.text
        assert "exporter failed" not in caplog.text

    @pytest.mark.asyncio
    async def test_hostile_span_name_sanitization_cannot_abort_caller(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        tracer = _RecordingTracer()
        monkeypatch.setattr(tracing, "_get_tracer", lambda: tracer)

        def broken_name_policy(
            _value: object,
            _allowed: object,
            *,
            fallback: str,
        ) -> str:
            assert fallback == "agent.call"
            raise RuntimeError(f"name parser saw {SECRET}")

        monkeypatch.setattr(
            telemetry_safety,
            "allowlisted_telemetry_label",
            broken_name_policy,
        )

        @trace_agent(cast(str, object()))
        async def fn() -> int:
            return 42

        with caplog.at_level("WARNING", logger="maistro.telemetry"):
            assert await fn() == 42

        assert tracer.started == [("telemetry.operation", False, False)]
        assert caplog.text.count("span name validation failed") == 1
        assert "error_type=RuntimeError" in caplog.text
        assert SECRET not in caplog.text

    @pytest.mark.asyncio
    async def test_broken_error_telemetry_cannot_mask_original_exception(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        tracer = _RecordingTracer(_RecordingSpan(writes_raise=True), exit_raises=True)
        monkeypatch.setattr(tracing, "_get_tracer", lambda: tracer)
        original = LookupError("application failure")

        @trace_agent("my-agent")
        async def fn() -> None:
            raise original

        with pytest.raises(LookupError) as exc_info:
            await fn()
        assert exc_info.value is original

    @pytest.mark.asyncio
    async def test_wraps_preserves_function_metadata(self) -> None:
        @trace_agent("my-agent")
        async def my_named_fn() -> None:
            """Docstring."""

        assert my_named_fn.__name__ == "my_named_fn"
        assert my_named_fn.__doc__ == "Docstring."
