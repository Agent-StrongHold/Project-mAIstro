from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class TelemetryPort(Protocol):
    def trace(self, **kwargs: Any) -> AbstractContextManager[Any]: ...
    def generation(self, **kwargs: Any) -> AbstractContextManager[Any]: ...
