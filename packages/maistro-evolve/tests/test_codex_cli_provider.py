from __future__ import annotations

import sys
from pathlib import Path

import pytest

from maistro_evolve.providers import CodexCliProvider


def _fake_codex(tmp_path: Path) -> tuple[str, ...]:
    script = tmp_path / "fake_codex.py"
    script.write_text(
        """
import pathlib
import sys

args = sys.argv[1:]
output = pathlib.Path(args[args.index("--output-last-message") + 1])
prompt = sys.stdin.read()
output.write_text(f"ANSWER:{prompt}", encoding="utf-8")
""".strip(),
        encoding="utf-8",
    )
    return sys.executable, str(script)


@pytest.mark.asyncio
async def test_codex_provider_matches_evolve_llm_call_shape(tmp_path: Path) -> None:
    provider = CodexCliProvider(command_prefix=_fake_codex(tmp_path))

    response = await provider("hello", temperature=0.0, max_tokens=20)

    assert response == "ANSWER:hello"


@pytest.mark.asyncio
async def test_codex_provider_passes_model_and_read_only_flags(tmp_path: Path) -> None:
    script = tmp_path / "inspect_args.py"
    script.write_text(
        """
import pathlib
import sys

args = sys.argv[1:]
output = pathlib.Path(args[args.index("--output-last-message") + 1])
output.write_text("|".join(args), encoding="utf-8")
""".strip(),
        encoding="utf-8",
    )
    provider = CodexCliProvider(model="gpt-5.4-mini", command_prefix=(sys.executable, str(script)))

    response = await provider("hello")

    assert "--sandbox|read-only" in response
    assert "--skip-git-repo-check" in response
    assert "--model|gpt-5.4-mini" in response
