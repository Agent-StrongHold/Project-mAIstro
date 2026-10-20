"""Tests for the OpenClaw and Pi harness_runner providers (issue #1613, M1-D).

The near side must be the real provider seam; the far side may be faked. These
tests inject an in-memory sandbox (fake far side) and assert the *real* adapter
behavior: one outbound task through the OpenClaw gateway, one Pi print-mode
coding-agent turn, correct quoting/flags, OpenAI-shaped envelopes, and
microVM wiring that points the harness at the caller's workspace.
"""

from __future__ import annotations

from maistro.agents.spec.agent_spec import AgentRole, AgentSpec
from maistro.capabilities import (
    OpenClawHarnessRunner,
    PiHarnessRunner,
    openclaw_microvm_factory,
    openclaw_microvm_runner,
    pi_microvm_factory,
    pi_microvm_runner,
)
from maistro.capabilities.providers.subprocess_harness import _Session
from maistro.capabilities.slots.harness_runner import SLOT_NAME
from maistro.tools.sandbox.microvm import MicroVMRunSpec, MicroVMSandbox


def _spec() -> AgentSpec:
    return AgentSpec(role=AgentRole.CODER, task_id="t", subtask_id="s", description="d")


class _FakeSandbox:
    def __init__(self, result: tuple[int, str] = (0, "harness done")) -> None:
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


# --- OpenClaw: one outbound task through the gateway --------------------------


class TestOpenClawBuildCommand:
    def test_one_outbound_gateway_task(self) -> None:
        runner = OpenClawHarnessRunner(sandbox_factory=_factory(_FakeSandbox()))
        cmd = runner.build_command(
            _session(_FakeSandbox()), [{"role": "user", "content": "deploy the checklist"}]
        )
        assert cmd.startswith("openclaw agent --message ")
        assert "'deploy the checklist'" in cmd

    def test_agent_and_pinned_session_flags(self) -> None:
        runner = OpenClawHarnessRunner(
            sandbox_factory=_factory(_FakeSandbox()),
            agent="personal",
            session="gw-sess-1",
        )
        cmd = runner.build_command(_session(_FakeSandbox()), [{"role": "user", "content": "go"}])
        assert "--agent personal" in cmd
        assert "--session gw-sess-1" in cmd

    def test_system_messages_excluded_and_prompt_quoted(self) -> None:
        runner = OpenClawHarnessRunner(sandbox_factory=_factory(_FakeSandbox()))
        cmd = runner.build_command(
            _session(_FakeSandbox()),
            [
                {"role": "system", "content": "INTERNAL"},
                {"role": "user", "content": "say hi; then rm -rf /"},
            ],
        )
        assert "INTERNAL" not in cmd
        # shell metacharacters stay inside one quoted argument
        assert "'say hi; then rm -rf /'" in cmd

    def test_extra_args_passed_through(self) -> None:
        runner = OpenClawHarnessRunner(
            sandbox_factory=_factory(_FakeSandbox()), extra_args=["--local"]
        )
        cmd = runner.build_command(
            _session(_FakeSandbox()), [{"role": "user", "content": "two words"}]
        )
        # --message consumes its value; operator flags follow it
        assert cmd == "openclaw agent --message 'two words' --local"


class TestOpenClawProviderSurface:
    def test_identity(self) -> None:
        runner = OpenClawHarnessRunner(sandbox_factory=_factory(_FakeSandbox()))
        assert runner.name == "openclaw"
        assert runner.slot == SLOT_NAME
        assert runner.requires() == ("openclaw",)

    async def test_healthcheck_reflects_binary_presence(self) -> None:
        healthy = OpenClawHarnessRunner(
            sandbox_factory=_factory(_FakeSandbox((0, "/usr/bin/openclaw")))
        )
        assert (await healthy.healthcheck()).healthy is True

        missing = OpenClawHarnessRunner(sandbox_factory=_factory(_FakeSandbox((1, ""))))
        assert (await missing.healthcheck()).healthy is False

    async def test_send_returns_openai_envelope_from_gateway_turn(self) -> None:
        sandbox = _FakeSandbox((0, "gateway task complete"))
        runner = OpenClawHarnessRunner(sandbox_factory=_factory(sandbox))
        sid = await runner.start_session(_spec(), workdir="/repos/proj")
        env = await runner.send(sid, [{"role": "user", "content": "run the task"}])
        assert env["choices"][0]["message"]["content"] == "gateway task complete"
        assert env["exit_code"] == 0
        assert sandbox.commands and sandbox.commands[0].startswith("openclaw agent --message")


# --- Pi: one coding-agent print-mode turn -------------------------------------


class TestPiBuildCommand:
    def test_print_mode_turn_is_non_interactive(self) -> None:
        runner = PiHarnessRunner(sandbox_factory=_factory(_FakeSandbox()))
        cmd = runner.build_command(
            _session(_FakeSandbox()), [{"role": "user", "content": "add a regression test"}]
        )
        assert cmd.startswith("pi -p ")
        assert "'add a regression test'" in cmd

    def test_provider_and_model_flags(self) -> None:
        runner = PiHarnessRunner(
            sandbox_factory=_factory(_FakeSandbox()),
            provider="anthropic",
            model="claude-opus-4-8",
        )
        cmd = runner.build_command(_session(_FakeSandbox()), [{"role": "user", "content": "go"}])
        assert "--provider anthropic" in cmd
        assert "--model claude-opus-4-8" in cmd

    def test_system_messages_excluded_and_prompt_quoted(self) -> None:
        runner = PiHarnessRunner(sandbox_factory=_factory(_FakeSandbox()))
        cmd = runner.build_command(
            _session(_FakeSandbox()),
            [
                {"role": "system", "content": "SECRET CONTEXT"},
                {"role": "user", "content": "fix it & echo done"},
            ],
        )
        assert "SECRET CONTEXT" not in cmd
        assert "'fix it & echo done'" in cmd

    def test_extra_args_passed_through(self) -> None:
        runner = PiHarnessRunner(
            sandbox_factory=_factory(_FakeSandbox()), extra_args=["--no-session"]
        )
        cmd = runner.build_command(_session(_FakeSandbox()), [{"role": "user", "content": "x"}])
        assert "--no-session" in cmd


class TestPiProviderSurface:
    def test_identity(self) -> None:
        runner = PiHarnessRunner(sandbox_factory=_factory(_FakeSandbox()))
        assert runner.name == "pi"
        assert runner.slot == SLOT_NAME
        assert runner.requires() == ("pi",)

    async def test_healthcheck_reflects_binary_presence(self) -> None:
        healthy = PiHarnessRunner(sandbox_factory=_factory(_FakeSandbox((0, "/usr/local/bin/pi"))))
        assert (await healthy.healthcheck()).healthy is True

        missing = PiHarnessRunner(sandbox_factory=_factory(_FakeSandbox((1, ""))))
        assert (await missing.healthcheck()).healthy is False

    async def test_send_returns_openai_envelope_from_print_turn(self) -> None:
        sandbox = _FakeSandbox((0, "edited tests/test_x.py"))
        runner = PiHarnessRunner(sandbox_factory=_factory(sandbox))
        sid = await runner.start_session(_spec(), workdir="/repos/proj")
        env = await runner.send(sid, [{"role": "user", "content": "add tests"}])
        assert env["choices"][0]["message"]["content"] == "edited tests/test_x.py"
        assert env["exit_code"] == 0
        assert sandbox.commands and sandbox.commands[0].startswith("pi -p")


# --- microVM wiring (point each harness at a real workspace) ------------------


class _FakeLauncher:
    def __init__(self) -> None:
        self.specs: list[MicroVMRunSpec] = []

    async def run(self, spec: MicroVMRunSpec) -> tuple[int, str]:
        self.specs.append(spec)
        return (0, "vm-ran")


class TestOpenClawMicroVMWiring:
    async def test_factory_boots_microvm_at_workdir(self) -> None:
        launcher = _FakeLauncher()
        factory = openclaw_microvm_factory(launcher, env={"OPENCLAW_GATEWAY_TOKEN": "t"})
        sandbox = await factory("/repos/target")
        assert isinstance(sandbox, MicroVMSandbox)
        code, out = await sandbox.exec("openclaw agent --message 'hi'")
        assert code == 0 and out == "vm-ran"
        assert launcher.specs[0].workspace == "/repos/target"
        # gateway credentials ride the operator-wired trusted env, not the turn
        assert launcher.specs[0].env == {"OPENCLAW_GATEWAY_TOKEN": "t"}

    async def test_runner_convenience_end_to_end(self) -> None:
        launcher = _FakeLauncher()
        runner = openclaw_microvm_runner(launcher, agent="personal")
        sid = await runner.start_session(_spec(), workdir="/repos/app")
        env = await runner.send(sid, [{"role": "user", "content": "ship it"}])
        assert env["choices"][0]["message"]["content"] == "vm-ran"
        assert launcher.specs[-1].workspace == "/repos/app"
        assert "--agent personal" in launcher.specs[-1].command


class TestPiMicroVMWiring:
    async def test_factory_boots_microvm_at_workdir(self) -> None:
        launcher = _FakeLauncher()
        factory = pi_microvm_factory(launcher, env={"ANTHROPIC_API_KEY": "k"})
        sandbox = await factory("/repos/target")
        assert isinstance(sandbox, MicroVMSandbox)
        code, out = await sandbox.exec("pi -p 'hi'")
        assert code == 0 and out == "vm-ran"
        assert launcher.specs[0].workspace == "/repos/target"
        assert launcher.specs[0].env == {"ANTHROPIC_API_KEY": "k"}

    async def test_runner_convenience_end_to_end(self) -> None:
        launcher = _FakeLauncher()
        runner = pi_microvm_runner(launcher, model="claude-opus-4-8")
        sid = await runner.start_session(_spec(), workdir="/repos/app")
        env = await runner.send(sid, [{"role": "user", "content": "refactor"}])
        assert env["choices"][0]["message"]["content"] == "vm-ran"
        assert launcher.specs[-1].workspace == "/repos/app"
        assert "--model claude-opus-4-8" in launcher.specs[-1].command
