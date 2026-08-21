"""BuilderSession — per-coding-session state for the builders DAG."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from maistro_bootstrap.builders.sandbox import BuilderSandbox


@dataclass
class BuilderSession:
    """Holds the sandbox and conversation history for one coding session."""

    # The `BuilderSandbox` protocol, not the concrete local sandbox — the RSI
    # loop drops a `ContainerBuilderSandbox` in here for ADR-093 isolation.
    sandbox: BuilderSandbox
    messages: list[dict[str, Any]] = field(default_factory=list)
    workspace_path: Path | None = None

    def add_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def add_assistant(self, text: str) -> None:
        self.messages.append({"role": "assistant", "content": text})

    def clear_history(self) -> None:
        self.messages.clear()
