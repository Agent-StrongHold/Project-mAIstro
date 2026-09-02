"""Security contract for Hive's external OpenTelemetry boundary."""

from __future__ import annotations

import logging
from types import TracebackType
from typing import Any

import adapters.telemetry_langfuse as telemetry
import pytest

from maistro.observability.correlation import bind_execution_context
from maistro.observability.telemetry_safety import sanitize_telemetry_label
from maistro.observability.tiers import pii_unexpected_match_total

_CREDENTIAL_PARTS = (
    "sk-",
    "live_ABCDE",
    "FGHIJKLMNO",
    "PQRSTUVWXY",
    "Z123456",
)
SECRET = "".join(_CREDENTIAL_PARTS)
EMAIL = "alice.private@example.com"


class _RecordingSpan:
    def __init__(
        self,
        *,
        attributes_raise: bool = False,
        status_raises: bool = False,
    ) -> None:
        self.attributes: dict[str, object] = {}
        self.statuses: list[object] = []
        self._attributes_raise = attributes_raise
        self._status_raises = status_raises

    def set_attribute(self, key: str, value: object) -> None:
        if self._attributes_raise:
            raise RuntimeError(f"attribute exporter failed {SECRET}")
        self.attributes[key] = value

    def set_status(self, status: object, description: str | None = None) -> None:
        if self._status_raises:
            raise RuntimeError(f"status exporter failed {SECRET}")
        self.statuses.append((status, description))


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
            raise RuntimeError(f"span exporter failed {SECRET}")


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
            raise RuntimeError("tracer start failed")
        self.started.append((name, record_exception, set_status_on_exception))
        return self.manager


@pytest.fixture(autouse=True)
def _fresh_adapter_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(telemetry, "_tracer", None)
    monkeypatch.setattr(telemetry, "_initialization_attempted", False)
    monkeypatch.setattr(telemetry, "_REPORTED_CATEGORIES", set())


def test_payloads_user_identity_and_raw_errors_are_never_exported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracer = _RecordingTracer()
    monkeypatch.setattr(telemetry, "_init_tracer", lambda: tracer)

    with (
        bind_execution_context(run_id="run-123", request_id="request-456"),
        telemetry.trace_llm(
            "chat_completion",
            model="safe-model",
            allowed_models={"safe-model"},
            user_id=EMAIL,
            metadata={
                "tool_name": "jira_lookup",
                "tool_args": {"api_key": SECRET},
                "prompt": f"contact {EMAIL}",
                "iteration": 2,
                "streaming": True,
            },
            allowed_tool_names={"jira_lookup"},
        ) as context,
    ):
        context["input"] = f"prompt {EMAIL} {SECRET}"
        context["output"] = f"completion {SECRET}"
        context["tool_calls"] = [{"arguments": {"api_key": SECRET}}]
        context["error"] = f"raw provider error {SECRET}"
        context["tokens"] = 37

    assert tracer.span.attributes == {
        "gen_ai.system": "litellm",
        "gen_ai.request.model": "safe-model",
        "fantasia.user.present": True,
        "fantasia.tool_name": "jira_lookup",
        "fantasia.iteration": 2,
        "fantasia.streaming": True,
        "gen_ai.usage.total_tokens": 37,
        "error.type": "application_error",
    }
    exported = repr((tracer.started, tracer.span.attributes, tracer.span.statuses))
    assert EMAIL not in exported
    assert SECRET not in exported
    assert "raw provider error" not in exported
    assert "gen_ai.prompt" not in tracer.span.attributes
    assert "gen_ai.completion" not in tracer.span.attributes
    assert "user.id" not in tracer.span.attributes
    assert tracer.started == [("chat_completion", False, False)]
    assert tracer.manager.exit_args == [(None, None, None)]


def test_wired_pii_and_secret_filters_protect_allowed_string_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracer = _RecordingTracer()
    monkeypatch.setattr(telemetry, "_init_tracer", lambda: tracer)

    with telemetry.trace_llm(
        "chat_completion",
        model=EMAIL,
        allowed_models={EMAIL},
        metadata={"tool_name": SECRET},
        allowed_tool_names={SECRET},
    ):
        pass

    assert tracer.span.attributes["gen_ai.request.model"] == "other"
    assert tracer.span.attributes["fantasia.tool_name"] == "unregistered"
    assert EMAIL not in repr(tracer.span.attributes)
    assert SECRET not in repr(tracer.span.attributes)


def test_tracer_failure_keeps_success_and_logs_no_payload(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def broken_init() -> None:
        raise RuntimeError(f"exporter rejected {SECRET}")

    monkeypatch.setattr(telemetry, "_init_tracer", broken_init)

    with (
        caplog.at_level(logging.WARNING, logger="hive.telemetry"),
        telemetry.trace_llm("chat_completion", user_id=EMAIL) as context,
    ):
        context["input"] = SECRET
        result = {"ok": True}

    assert result == {"ok": True}
    assert "continuing without telemetry" in caplog.text
    assert SECRET not in caplog.text
    assert EMAIL not in caplog.text


def test_hostile_metadata_and_finalizer_failures_keep_caller_behavior(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    tracer = _RecordingTracer()
    monkeypatch.setattr(telemetry, "_init_tracer", lambda: tracer)

    class _HostileMetadata(dict[str, Any]):
        def __bool__(self) -> bool:
            raise ValueError(f"metadata failure {SECRET}")

    with (
        caplog.at_level(logging.WARNING, logger="hive.telemetry"),
        telemetry.trace_llm(
            "chat_completion",
            metadata=_HostileMetadata(),
        ),
    ):
        product_result = "unchanged"

    assert product_result == "unchanged"
    assert "error_type=ValueError" in caplog.text
    assert SECRET not in caplog.text

    monkeypatch.setattr(telemetry, "_REPORTED_CATEGORIES", set())
    monkeypatch.setattr(
        telemetry,
        "mark_span_error",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError(f"finalizer {SECRET}")),
    )
    with (
        caplog.at_level(logging.WARNING, logger="hive.telemetry"),
        telemetry.trace_llm("chat_completion") as context,
    ):
        context["error"] = SECRET

    assert caplog.text.count("error_type=RuntimeError") == 1
    assert SECRET not in caplog.text


def test_span_write_and_export_failures_keep_successful_result(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    tracer = _RecordingTracer(_RecordingSpan(attributes_raise=True), exit_raises=True)
    monkeypatch.setattr(telemetry, "_init_tracer", lambda: tracer)

    with caplog.at_level(logging.WARNING, logger="hive.telemetry"):
        for _ in range(3):
            with telemetry.trace_llm(
                "chat_completion",
                model="safe-model",
                allowed_models={"safe-model"},
            ):
                result = "successful product result"

    assert result == "successful product result"
    assert caplog.text.count("span attribute write failed") == 1
    assert caplog.text.count("span close failed") == 1
    assert caplog.text.count("error_type=RuntimeError") == 2
    assert SECRET not in caplog.text


def test_telemetry_failures_cannot_mask_original_application_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    span = _RecordingSpan(status_raises=True)
    tracer = _RecordingTracer(span, exit_raises=True)
    monkeypatch.setattr(telemetry, "_init_tracer", lambda: tracer)
    original = LookupError(f"application failure {SECRET}")

    with (
        pytest.raises(LookupError) as exc_info,
        telemetry.trace_llm("chat_completion"),
    ):
        stack_only_value = "private-stack-local"
        assert stack_only_value
        raise original

    assert exc_info.value is original
    exported = repr((span.attributes, span.statuses, tracer.manager.exit_args))
    assert SECRET not in exported
    assert "application failure" not in exported
    assert "private-stack-local" not in exported
    assert span.attributes["error.type"] == "application_error"
    assert tracer.manager.exit_args == [(None, None, None)]


def test_case_variants_export_one_lowercase_allowlisted_encoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracer = _RecordingTracer()
    monkeypatch.setattr(telemetry, "_init_tracer", lambda: tracer)

    with telemetry.trace_llm(
        "CHAT_COMPLETION",
        model="APPROVED/MODEL",
        allowed_models={"Approved/Model"},
        metadata={"tool_name": "CHECK_BLOCKERS"},
        allowed_tool_names={"check_blockers"},
    ):
        pass

    assert tracer.started == [("chat_completion", False, False)]
    assert tracer.span.attributes["gen_ai.request.model"] == "approved/model"
    assert tracer.span.attributes["fantasia.tool_name"] == "check_blockers"


def test_untrusted_model_and_tool_labels_have_fixed_cardinality(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exported: set[tuple[object, object]] = set()

    for index in range(200):
        tracer = _RecordingTracer()
        monkeypatch.setattr(telemetry, "_init_tracer", lambda tracer=tracer: tracer)
        with telemetry.trace_llm(
            "chat_completion",
            model=f"attacker-model-{index}",
            allowed_models={"configured-model"},
            metadata={"tool_name": f"attacker-tool-{index}"},
            allowed_tool_names={"registered_tool"},
        ):
            pass
        exported.add(
            (
                tracer.span.attributes["gen_ai.request.model"],
                tracer.span.attributes["fantasia.tool_name"],
            )
        )

    assert exported == {("other", "unregistered")}


def test_telemetry_pii_rejection_does_not_increment_application_pii_metric() -> None:
    before = pii_unexpected_match_total.collect()

    assert sanitize_telemetry_label(EMAIL) == "redacted"

    assert pii_unexpected_match_total.collect() == before
