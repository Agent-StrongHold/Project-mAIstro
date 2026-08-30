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
