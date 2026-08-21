"""Tests tied to SPEC.md §9 (agent-backed apply_patch drivers) acceptance criteria
applyagents-1..4."""

from __future__ import annotations

import pytest

from maistro_rsi.apply_agents import (
    OPENCODE_TEMPLATE,
    ApplyPatchError,
    command_apply_patch,
)


class _FakeSandbox:
    def __init__(self, result: tuple[int, str] = (0, "ok")) -> None:
        self.result = result
        self.commands: list[str] = []

    async def exec(self, command: str, timeout: int = 60) -> tuple[int, str]:
        self.commands.append(command)
        return self.result


class TestCommandApplyPatch:
    @pytest.mark.asyncio
    async def test_prompt_is_shell_quoted(self):
        """applyagents-1: shell metacharacters in the prompt cannot break out
        of their argument position."""
        sandbox = _FakeSandbox()
        patch = command_apply_patch("fix it; rm -rf /")
        await patch(sandbox, "/ws")
        assert sandbox.commands == ["opencode run --auto 'fix it; rm -rf /'"]

    @pytest.mark.asyncio
    async def test_runs_via_sandbox_exec(self):
        """applyagents-2: the agent command executes inside the sandbox, not a
        bare host shell call."""
        sandbox = _FakeSandbox()
        patch = command_apply_patch("do the thing", template="custom {prompt}")
        await patch(sandbox, "/ws")
        assert sandbox.commands == ["custom 'do the thing'"]

    @pytest.mark.asyncio
    async def test_nonzero_exit_raises_apply_patch_error(self):
        """applyagents-3: a failed agent command raises, carrying exit code +
        output tail, rather than silently producing an empty patch."""
        sandbox = _FakeSandbox((1, "agent crashed"))
        patch = command_apply_patch("do it")
        with pytest.raises(ApplyPatchError, match="exited 1"):
            await patch(sandbox, "/ws")

    @pytest.mark.asyncio
    async def test_model_placeholder_substituted_when_present(self):
        """applyagents-4: a {model} placeholder is filled from the per-cycle
        model arg, shlex-quoted."""
        sandbox = _FakeSandbox()
        patch = command_apply_patch("go", template="opencode run --model {model} --auto {prompt}")
        await patch(sandbox, "/ws", "anthropic/claude-opus-4-8")
        assert sandbox.commands == ["opencode run --model anthropic/claude-opus-4-8 --auto go"]

    @pytest.mark.asyncio
    async def test_model_placeholder_empty_when_none(self):
        """applyagents-4: a None model substitutes empty string, not the
        literal 'None'."""
        sandbox = _FakeSandbox()
        patch = command_apply_patch("go", template="agent --model={model} {prompt}")
        await patch(sandbox, "/ws", None)
        assert sandbox.commands == ["agent --model= go"]

    @pytest.mark.asyncio
    async def test_default_template_is_opencode(self):
        sandbox = _FakeSandbox()
        patch = command_apply_patch("hello")
        await patch(sandbox, "/ws")
        assert sandbox.commands[0].startswith("opencode run --auto")
        assert OPENCODE_TEMPLATE == "opencode run --auto {prompt}"
