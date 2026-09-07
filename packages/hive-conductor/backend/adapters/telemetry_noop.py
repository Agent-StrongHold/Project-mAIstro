from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext
from typing import Any

from protocols.telemetry import TelemetryPort


class NoopTelemetry(TelemetryPort):
    """Telemetry adapter that preserves tracing call sites when tracing is disabled.

    Explicitly subclasses the port so an offline deployment and a traced one
    present the same seam — the call site cannot tell, and must not be able to
    tell, which backend it holds (#63).
    """

    def trace(self, **kwargs: Any) -> AbstractContextManager[Any]:
        """Return a no-op context manager for generic spans."""
        del kwargs
        return nullcontext()

    def generation(self, **kwargs: Any) -> AbstractContextManager[Any]:
        """Return a no-op context manager for LLM generation spans."""
        del kwargs
        return nullcontext()
