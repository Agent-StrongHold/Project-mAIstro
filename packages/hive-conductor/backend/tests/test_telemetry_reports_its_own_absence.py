"""Tracing off and tracing broken are different answers (#668).

`_init_tracer` returned `None` for both "no endpoint configured" and "an
endpoint is configured and OpenTelemetry is not installed". The second is the
state the shipped image was left in by #514, which removed `langfuse` -- the
package that had been supplying the OpenTelemetry API, SDK and exporter
transitively -- without giving the build any way to put them back.

So an operator who set `OTEL_EXPORTER_OTLP_ENDPOINT` on a container built from
`packages/hive-conductor/Dockerfile` saw no traces, no error, and nothing to
distinguish that from having left tracing switched off. A telemetry adapter
that cannot report its own absence is the one failure mode it must not have.
"""

from __future__ import annotations

import builtins
import logging
import runpy
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import adapters.telemetry_langfuse as telemetry
import pytest


@pytest.fixture(autouse=True)
def _fresh_module_state(monkeypatch) -> None:
    """The adapter's process-global one-shot state is isolated per test."""
    monkeypatch.setattr(telemetry, "_tracer", None)
    monkeypatch.setattr(telemetry, "_initialization_attempted", False)
    monkeypatch.setattr(telemetry, "_REPORTED_CATEGORIES", set())


def _without_opentelemetry(monkeypatch) -> None:
    monkeypatch.setattr(telemetry, "_OTEL_AVAILABLE", False)
    monkeypatch.setattr(telemetry, "_OTEL_IMPORT_ERROR_TYPE", ImportError)


def test_no_endpoint_is_silent(monkeypatch, caplog) -> None:
    """The ordinary state. Nobody asked for tracing, so nothing is wrong and
    nothing is said -- a line here would fire on every deployment that never
    wanted traces."""
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)

    with caplog.at_level(logging.DEBUG, logger="hive.telemetry"):
        assert telemetry._init_tracer() is None

    assert caplog.text == ""


def test_a_configured_endpoint_with_no_packages_says_so(monkeypatch, caplog) -> None:
    """The case that was silent. The operator asked for traces and cannot get
    them; the log is the only place that fact exists."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://otel.example.com")
    _without_opentelemetry(monkeypatch)

    with caplog.at_level(logging.ERROR, logger="hive.telemetry"):
        assert telemetry._init_tracer() is None

    assert "could not be loaded" in caplog.text
    assert "observability" in caplog.text, "the message names what to install"
    assert "INSTALL_OBSERVABILITY" in caplog.text, "and how to get it into the image"
    assert "error_type=ImportError" in caplog.text


def test_the_report_is_made_once_per_process(monkeypatch, caplog) -> None:
    """`_init_tracer` runs on every traced call. A line per LLM request would
    bury the one time it mattered under its own repetition."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://otel.example.com")
    _without_opentelemetry(monkeypatch)

    with caplog.at_level(logging.ERROR, logger="hive.telemetry"):
        for _ in range(5):
            telemetry._init_tracer()

    assert caplog.text.count("could not be loaded") == 1


def test_failure_category_reporting_is_thread_safe(caplog) -> None:
    with (
        caplog.at_level(logging.WARNING, logger="hive.telemetry"),
        ThreadPoolExecutor(max_workers=16) as executor,
    ):
        list(
            executor.map(lambda _index: telemetry._report_once("runtime", RuntimeError), range(64))
        )

    assert caplog.text.count("failed; continuing without telemetry") == 1


def test_tracing_stays_a_no_op_when_it_cannot_start(monkeypatch) -> None:
    """Reporting the absence must not change what the caller gets. A missing
    exporter is not a reason to fail an LLM call."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://otel.example.com")
    _without_opentelemetry(monkeypatch)

    with telemetry.trace_llm("unit", model="stub") as ctx:
        ctx["output"] = "still runs"

    assert ctx == {"output": "still runs"}


def _stub_opentelemetry(monkeypatch, *, resource_raises: bool = False) -> object:
    """Install a minimal OpenTelemetry surface, so both post-import paths run.

    CI does not install the observability extra -- that is the whole point of it
    being an extra -- so every test above takes the ImportError branch and the
    setup path is unreachable there. Stubbing the five optional module-level
    imports is what lets that path be exercised at all.
    """

    class _Tracer:
        pass

    tracer = _Tracer()

    class _Resource:
        @staticmethod
        def create(_attrs: dict[str, Any]) -> object:
            if resource_raises:
                raise RuntimeError("the exporter refused this configuration")
            return object()

    class _Provider:
        def __init__(self, resource: object) -> None:
            self.resource = resource

        def add_span_processor(self, _processor: object) -> None:
            return None

    trace_api = SimpleNamespace(
        set_tracer_provider=lambda _provider: None,
        get_tracer=lambda _name: tracer,
    )
    monkeypatch.setattr(telemetry, "_OTEL_AVAILABLE", True)
    monkeypatch.setattr(telemetry, "otel_trace", trace_api, raising=False)
    monkeypatch.setattr(telemetry, "Resource", _Resource, raising=False)
    monkeypatch.setattr(telemetry, "TracerProvider", _Provider, raising=False)
    monkeypatch.setattr(
        telemetry,
        "OTLPSpanExporter",
        lambda **_kwargs: object(),
        raising=False,
    )
    monkeypatch.setattr(
        telemetry,
        "BatchSpanProcessor",
        lambda _exporter: object(),
        raising=False,
    )
    return tracer


def test_a_configured_endpoint_with_the_packages_builds_a_tracer(monkeypatch) -> None:
    """The path that is the reason for all of this: it works, and quietly."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://otel.example.com")
    tracer = _stub_opentelemetry(monkeypatch)

    assert telemetry._init_tracer() is tracer
    assert telemetry._init_tracer() is tracer


def test_a_setup_failure_is_reported_as_its_own_thing(monkeypatch, caplog) -> None:
    """A bad endpoint or a refused exporter is not a missing package, and
    telling an operator to install something they already have would send them
    after the wrong problem."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://otel.example.com")
    _stub_opentelemetry(monkeypatch, resource_raises=True)

    with caplog.at_level(logging.ERROR, logger="hive.telemetry"):
        assert telemetry._init_tracer() is None

    assert "could not be initialised" in caplog.text
    assert "could not be loaded" not in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "the exporter refused" not in caplog.text


def test_a_repeated_setup_failure_is_also_reported_only_once(monkeypatch, caplog) -> None:
    """The same restraint as the missing-package report, and for the same
    reason: `_init_tracer` runs on every traced call, so a provider that keeps
    refusing would otherwise write a line per LLM request."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://otel.example.com")
    _stub_opentelemetry(monkeypatch, resource_raises=True)

    with caplog.at_level(logging.ERROR, logger="hive.telemetry"):
        for _ in range(4):
            assert telemetry._init_tracer() is None

    assert caplog.text.count("could not be initialised") == 1


def test_failed_provider_shutdown_falls_back_to_processor_shutdown() -> None:
    processor_stopped = False

    class _Provider:
        @staticmethod
        def shutdown() -> None:
            raise RuntimeError("provider shutdown failed")

    class _Processor:
        @staticmethod
        def shutdown() -> None:
            nonlocal processor_stopped
            processor_stopped = True

    telemetry._shutdown_failed_initialization(
        _Provider(),
        _Processor(),
        processor_added=True,
    )

    assert processor_stopped


def test_reporter_failure_and_unknown_category_are_fail_open(monkeypatch) -> None:
    telemetry._report_once("not-a-category", RuntimeError)
    monkeypatch.setattr(
        telemetry.logger,
        "log",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("logger failed")),
    )
    telemetry._report_once("runtime", RuntimeError)


def test_runtime_import_version_skew_is_fail_open(monkeypatch) -> None:
    real_import = builtins.__import__

    def skewed_import(name: str, *args: object, **kwargs: object) -> object:
        if name.startswith("opentelemetry"):
            raise RuntimeError("version skew carrying private details")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", skewed_import)
    namespace = runpy.run_path(str(Path(telemetry.__file__)))

    assert namespace["_OTEL_AVAILABLE"] is False
    assert namespace["_OTEL_IMPORT_ERROR_TYPE"] is RuntimeError


def test_optional_import_does_not_swallow_base_exception(monkeypatch) -> None:
    class ImportAborted(BaseException):
        pass

    real_import = builtins.__import__

    def aborted_import(name: str, *args: object, **kwargs: object) -> object:
        if name.startswith("opentelemetry"):
            raise ImportAborted
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", aborted_import)
    with pytest.raises(ImportAborted):
        runpy.run_path(str(Path(telemetry.__file__)))


def test_init_and_runtime_failures_each_report_once_without_messages(
    monkeypatch,
    caplog,
) -> None:
    credential_probe = "".join(("sk-", "live_ABCDE", "FGHIJKLMNO", "PQRSTUVWXY", "Z123456"))
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://otel.example.com")
    _stub_opentelemetry(monkeypatch, resource_raises=True)

    with caplog.at_level(logging.WARNING, logger="hive.telemetry"):
        assert telemetry._init_tracer() is None

        def broken_runtime_lookup() -> None:
            raise ValueError(f"runtime details {credential_probe}")

        monkeypatch.setattr(telemetry, "_init_tracer", broken_runtime_lookup)
        for _ in range(3):
            with telemetry.trace_llm("chat_completion"):
                pass

    assert caplog.text.count("could not be initialised") == 1
    assert caplog.text.count("failed; continuing without telemetry") == 1
    assert "error_type=RuntimeError" in caplog.text
    assert "error_type=ValueError" in caplog.text
    assert credential_probe not in caplog.text
    assert "runtime details" not in caplog.text


def test_failed_initialization_allocates_one_processor_across_threads(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://otel.example.com")
    created_processors = 0
    shut_down_processors = 0
    count_lock = threading.Lock()

    class _Resource:
        @staticmethod
        def create(_attrs: dict[str, Any]) -> object:
            return object()

    class _Provider:
        def __init__(self, resource: object) -> None:
            self.resource = resource

        def add_span_processor(self, _processor: object) -> None:
            return None

        def shutdown(self) -> None:
            nonlocal shut_down_processors
            with count_lock:
                shut_down_processors += 1

    class _Processor:
        def __init__(self, _exporter: object) -> None:
            nonlocal created_processors
            with count_lock:
                created_processors += 1

    trace_api = SimpleNamespace(
        set_tracer_provider=lambda _provider: None,
        get_tracer=lambda _name: (_ for _ in ()).throw(
            RuntimeError("late initialization failure with private details")
        ),
    )
    monkeypatch.setattr(telemetry, "_OTEL_AVAILABLE", True)
    monkeypatch.setattr(telemetry, "otel_trace", trace_api, raising=False)
    monkeypatch.setattr(telemetry, "Resource", _Resource, raising=False)
    monkeypatch.setattr(telemetry, "TracerProvider", _Provider, raising=False)
    monkeypatch.setattr(
        telemetry,
        "OTLPSpanExporter",
        lambda **_kwargs: object(),
        raising=False,
    )
    monkeypatch.setattr(telemetry, "BatchSpanProcessor", _Processor, raising=False)

    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(lambda _index: telemetry._init_tracer(), range(64)))

    assert results == [None] * 64
    assert created_processors == 1
    assert shut_down_processors == 1
