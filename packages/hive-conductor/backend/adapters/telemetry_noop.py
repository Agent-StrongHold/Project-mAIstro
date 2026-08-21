from __future__ import annotations

from contextlib import nullcontext
from typing import Any


class NoopTelemetry:
    """Telemetry adapter that preserves tracing call sites when tracing is disabled."""

    def trace(self, **kwargs: Any) -> Any:
        """Return a no-op context manager for generic spans."""
        return nullcontext()

    def generation(self, **kwargs: Any) -> Any:
        """Return a no-op context manager for LLM generation spans."""
        return nullcontext()
