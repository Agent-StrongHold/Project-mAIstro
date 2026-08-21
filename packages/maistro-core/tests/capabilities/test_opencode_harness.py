"""Tests for the opencode harness_runner provider (SPEC-208 §1-2)."""

from __future__ import annotations

from maistro.agents.spec.agent_spec import AgentRole, AgentSpec
from maistro.capabilities.providers.opencode import (
    OpencodeHarnessRunner,
    opencode_microvm_factory,
    opencode_microvm_runner,
)
from maistro.capabilities.providers.subprocess_harness import _Session
from maistro.capabilities.slots.harness_runner import SLOT_NAME
from maistro.tools.sandbox.microvm import MicroVMRunSpec, MicroVMSandbox


def _spec() -> AgentSpec:
    return AgentSpec(role=AgentRole.CODER, task_id="t", subtask_id="s", description="d")


class _FakeSandbox:
    def __init__(self, result: tuple[int, str] = (0, "opencode done")) -> None:
        self.result = result
        self.commands: list[str] = []

    async def exec(self, command: str, timeout: int = 60) -> tuple[int, str]:
        self.commands.append(command)
        return self.result


def _factory(sandbox: _FakeSandbox):
    workdirs: list[str] = []

    async def make(workdir: str) -> _FakeSandbox:
        workdirs.append(workdir)
        return sandbox

    make.workdirs = workdirs  # type: ignore[attr-defined]
    return make


def _session(sandbox: _FakeSandbox, workdir: str = "/repos/proj") -> _Session:
    return _Session(agent_spec=_spec(), workdir=workdir, sandbox=sandbox)  # type: ignore[arg-type]


# --- build_command ------------------------------------------------------------


class TestBuildCommand:
    def test_basic_invocation_is_non_interactive(self) -> None:
        runner = OpencodeHarnessRunner(sandbox_factory=_factory(_FakeSandbox()))
        cmd = runner.build_command(
            _session(_FakeSandbox()), [{"role": "user", "content": "fix bug"}]
        )
        assert cmd.startswith("opencode run --auto ")
        assert cmd.endswith("'fix bug'") or cmd.endswith("fix bug")

    def test_model_and_agent_flags(self) -> None:
        runner = OpencodeHarnessRunner(
            sandbox_factory=_factory(_FakeSandbox()),
            model="anthropic/claude-opus-4-8",
            agent="build",
        )
        cmd = runner.build_command(_session(_FakeSandbox()), [{"role": "user", "content": "go"}])
        assert "--model anthropic/claude-opus-4-8" in cmd
        assert "--agent build" in cmd

    def test_system_messages_excluded_and_prompt_quoted(self) -> None:
        runner = OpencodeHarnessRunner(sandbox_factory=_factory(_FakeSandbox()))
        cmd = runner.build_command(
            _session(_FakeSandbox()),
            [
                {"role": "system", "content": "IGNORE ME"},
                {"role": "user", "content": "a b; rm"},
            ],
        )
        assert "IGNORE ME" not in cmd
        # the shell-metachar-bearing prompt is quoted as one argument
        assert "'a b; rm'" in cmd

    def test_extra_args_passed_through(self) -> None:
        runner = OpencodeHarnessRunner(
            sandbox_factory=_factory(_FakeSandbox()), extra_args=["--variant", "high"]
        )
        cmd = runner.build_command(_session(_FakeSandbox()), [{"role": "user", "content": "x"}])
        assert "--variant high" in cmd


# --- provider surface ---------------------------------------------------------


class TestProviderSurface:
    def test_identity(self) -> None:
        runner = OpencodeHarnessRunner(sandbox_factory=_factory(_FakeSandbox()))
        assert runner.name == "opencode"
        assert runner.slot == SLOT_NAME
        assert runner.requires() == ("opencode",)

    async def test_healthcheck_reflects_binary_presence(self) -> None:
        healthy = OpencodeHarnessRunner(
            sandbox_factory=_factory(_FakeSandbox((0, "/usr/bin/opencode")))
        )
        assert (await healthy.healthcheck()).healthy is True

        missing = OpencodeHarnessRunner(sandbox_factory=_factory(_FakeSandbox((1, ""))))
        assert (await missing.healthcheck()).healthy is False

    async def test_send_returns_openai_envelope(self) -> None:
        sandbox = _FakeSandbox((0, "patched 2 files"))
        runner = OpencodeHarnessRunner(sandbox_factory=_factory(sandbox))
        sid = await runner.start_session(_spec(), workdir="/repos/proj")
        env = await runner.send(sid, [{"role": "user", "content": "fix"}])
        assert env["choices"][0]["message"]["content"] == "patched 2 files"
        assert env["exit_code"] == 0
        # the turn ran an opencode invocation inside the sandbox
        assert sandbox.commands and sandbox.commands[0].startswith("opencode run --auto")


# --- microVM wiring (point it at a repo) --------------------------------------


class _FakeLauncher:
    def __init__(self) -> None:
        self.specs: list[MicroVMRunSpec] = []

    async def run(self, spec: MicroVMRunSpec) -> tuple[int, str]:
        self.specs.append(spec)
        return (0, "vm-ran")


class TestMicroVMWiring:
    async def test_factory_boots_microvm_at_workdir(self) -> None:
        launcher = _FakeLauncher()
        factory = opencode_microvm_factory(launcher, env={"OPENCODE_API_KEY": "k"})
        sandbox = await factory("/repos/target")
        assert isinstance(sandbox, MicroVMSandbox)
        code, out = await sandbox.exec("opencode run --auto 'hi'")
        assert code == 0 and out == "vm-ran"
        # the VM's workspace is the repo we pointed it at; env is threaded in
        assert launcher.specs[0].workspace == "/repos/target"
        assert launcher.specs[0].env == {"OPENCODE_API_KEY": "k"}

    async def test_runner_convenience_end_to_end(self) -> None:
        launcher = _FakeLauncher()
        runner = opencode_microvm_runner(launcher, model="anthropic/claude-opus-4-8")
        sid = await runner.start_session(_spec(), workdir="/repos/app")
        env = await runner.send(sid, [{"role": "user", "content": "add tests"}])
        assert env["choices"][0]["message"]["content"] == "vm-ran"
        # opencode ran inside a microVM whose workspace is the pointed-at repo
        assert launcher.specs[-1].workspace == "/repos/app"
        assert "--model anthropic/claude-opus-4-8" in launcher.specs[-1].command
