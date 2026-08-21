"""Use an authenticated Codex CLI as an async Evolve model provider."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any


class CodexCliProvider:
    """Async `llm_call` adapter for controller-side Codex CLI execution."""

    def __init__(
        self,
        *,
        model: str | None = None,
        timeout_seconds: float = 120.0,
        command_prefix: Sequence[str] | None = None,
    ) -> None:
        executable = os.environ.get("MAISTRO_CODEX_EXECUTABLE", "codex")
        self._command_prefix = tuple(command_prefix or (executable, "exec"))
        self._model = model
        self._timeout_seconds = timeout_seconds

    async def __call__(
        self,
        prompt_or_messages: str | list[dict[str, Any]],
        **_: Any,
    ) -> str:
        prompt = _render_prompt(prompt_or_messages)
        with tempfile.TemporaryDirectory(prefix="maistro-codex-provider-") as temp_name:
            temp_dir = Path(temp_name)
            output_path = temp_dir / "last-message.txt"
            command = [
                *self._command_prefix,
                "--sandbox",
                "read-only",
                "--skip-git-repo-check",
                "--output-last-message",
                str(output_path),
            ]
            if self._model:
                command.extend(["--model", self._model])
            command.append("-")

            try:
                process = await asyncio.create_subprocess_exec(
                    *command,
                    cwd=temp_dir,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
            except (FileNotFoundError, OSError) as exc:
                raise RuntimeError(
                    "Codex CLI is unavailable. Install/authenticate Codex or set "
                    "MAISTRO_CODEX_EXECUTABLE."
                ) from exc

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(prompt.encode("utf-8")),
                    timeout=self._timeout_seconds,
                )
            except TimeoutError as exc:
                process.kill()
                await process.communicate()
                raise TimeoutError(
                    f"Codex CLI request exceeded {self._timeout_seconds} seconds"
                ) from exc

            if process.returncode != 0:
                detail = stderr.decode("utf-8", errors="replace")[-2000:]
                raise RuntimeError(
                    f"Codex CLI request failed with exit {process.returncode}: {detail}"
                )
            if not output_path.is_file():
                detail = stdout.decode("utf-8", errors="replace")[-2000:]
                raise RuntimeError(f"Codex CLI did not produce a final message: {detail}")
            return output_path.read_text(encoding="utf-8").strip()


def _render_prompt(prompt_or_messages: str | list[dict[str, Any]]) -> str:
    if isinstance(prompt_or_messages, str):
        return prompt_or_messages
    return (
        "Respond to the following conversation. Do not inspect files or use external tools. "
        "Return only the assistant response requested by the final user message.\n\n"
        + json.dumps(prompt_or_messages, ensure_ascii=True)
    )
