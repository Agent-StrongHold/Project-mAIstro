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
from typing import Any

import adapters.telemetry_langfuse as telemetry
import pytest


@pytest.fixture(autouse=True)
def _fresh_module_state(monkeypatch) -> None:
    """`_tracer` and `_reported` are process-global and this suite sets both."""
    monkeypatch.setattr(telemetry, "_tracer", None)
    monkeypatch.setattr(telemetry, "_reported", False)


def _without_opentelemetry(monkeypatch) -> None:
    real_import = builtins.__import__

    def blocked(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.startswith("opentelemetry"):
            raise ModuleNotFoundError(f"No module named {name!r}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)


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

    assert "not installed" in caplog.text
    assert "observability" in caplog.text, "the message names what to install"
    assert "INSTALL_OBSERVABILITY" in caplog.text, "and how to get it into the image"


def test_the_report_is_made_once_per_process(monkeypatch, caplog) -> None:
    """`_init_tracer` runs on every traced call. A line per LLM request would
    bury the one time it mattered under its own repetition."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://otel.example.com")
    _without_opentelemetry(monkeypatch)

    with caplog.at_level(logging.ERROR, logger="hive.telemetry"):
        for _ in range(5):
            telemetry._init_tracer()

    assert caplog.text.count("not installed") == 1


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
    code *after* the imports is unreachable there. Stubbing the five names
    `_init_tracer` imports is what lets the setup path be exercised at all.
    """
    import sys
    import types

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

    trace_mod = types.ModuleType("opentelemetry.trace")
    trace_mod.set_tracer_provider = lambda _p: None  # type: ignore[attr-defined]
    trace_mod.get_tracer = lambda _name: tracer  # type: ignore[attr-defined]

    root = types.ModuleType("opentelemetry")
    root.trace = trace_mod  # type: ignore[attr-defined]

    modules = {
        "opentelemetry": root,
        "opentelemetry.trace": trace_mod,
        "opentelemetry.exporter.otlp.proto.http.trace_exporter": types.ModuleType("x"),
        "opentelemetry.sdk.resources": types.ModuleType("r"),
        "opentelemetry.sdk.trace": types.ModuleType("t"),
        "opentelemetry.sdk.trace.export": types.ModuleType("e"),
    }
    modules["opentelemetry.exporter.otlp.proto.http.trace_exporter"].OTLPSpanExporter = (  # type: ignore[attr-defined]
        lambda **_kw: object()
    )
    modules["opentelemetry.sdk.resources"].Resource = _Resource  # type: ignore[attr-defined]
    modules["opentelemetry.sdk.trace"].TracerProvider = _Provider  # type: ignore[attr-defined]
    modules["opentelemetry.sdk.trace.export"].BatchSpanProcessor = lambda _e: object()  # type: ignore[attr-defined]

    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    return tracer


def test_a_configured_endpoint_with_the_packages_builds_a_tracer(monkeypatch) -> None:
    """The path that is the reason for all of this: it works, and quietly."""
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "https://otel.example.com")
    tracer = _stub_opentelemetry(monkeypatch)

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
    assert "not installed" not in caplog.text


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
