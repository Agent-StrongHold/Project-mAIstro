"""Tests for the codex_app_server harness_runner provider (issue #822).

Covers the provider seam itself plus the governed boundaries the issue names:
successful turn, streaming projection, tool request, denied effect, provider
crash, cancellation, and session cleanup — through both the raw provider and
``HarnessSessionManager`` (the canonical Binding -> policy -> Invocation path
a graph node's ``HarnessNodeExecutor`` builds on).
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro.agents.spec.agent_spec import AgentRole, AgentSpec
from maistro.capabilities import (
    HarnessSessionManager,
    Unavailable,
)
from maistro.capabilities.binding import Binding
from maistro.capabilities.bootstrap import default_capability_registry
from maistro.capabilities.effect_context import binding_scope_policy, new_effect_context
from maistro.capabilities.invocation import InMemoryInvocationStore
from maistro.capabilities.providers.codex_app_server import (
    PREFERRED_CODEX_PROVIDER,
    CodexAppServerHarnessRunner,
    CodexTurnError,
    codex_app_server_microvm_factory,
    codex_app_server_microvm_runner,
)
from maistro.capabilities.slots.harness_runner import SLOT_NAME, HarnessInputBlocked
from maistro.graph.harness_executor import HarnessExecutionError, HarnessNodeExecutor
from maistro.graph.types import AgentRole as GraphAgentRole
from maistro.graph.types import HarnessOutput
from maistro.policy import SequencePolicyEngine
from maistro.security._types import WardenVerdict
from maistro.tools.sandbox.microvm import MicroVMRunSpec, MicroVMSandbox


def _spec() -> AgentSpec:
    return AgentSpec(role=AgentRole.CODER, task_id="t", subtask_id="s", description="d")


_TURN_OK = (0, '{"content": "app server done", "actions": [], "exit_code": 0}')
_CREATE_OK = (0, '{"session_id": "codex-thread-123"}')


class _FakeSandbox:
    """Scripted SandboxExec fake: dispatches canned results by command prefix."""

    def __init__(
        self,
        results: dict[str, tuple[int, str]] | None = None,
        default: tuple[int, str] = _TURN_OK,
        *,
        fail_on: str | None = None,
    ) -> None:
        self.results = results or {}
        self.default = default
        self.commands: list[str] = []
        self.fail_on = fail_on
        self.destroyed = False

    async def exec(self, command: str, timeout: int = 60) -> tuple[int, str]:
        self.commands.append(command)
        if self.fail_on is not None and command.startswith(self.fail_on):
            raise RuntimeError("vm crashed mid-turn")
        for prefix, result in self.results.items():
            if command.startswith(prefix):
                return result
        return self.default

    async def destroy(self) -> None:
        self.destroyed = True


def _factory(sandbox: _FakeSandbox):
    workdirs: list[str] = []

    async def make(workdir: str) -> _FakeSandbox:
        workdirs.append(workdir)
        return sandbox

    make.workdirs = workdirs  # type: ignore[attr-defined]
    return make


def _runner(sandbox: _FakeSandbox, **kwargs: Any) -> CodexAppServerHarnessRunner:
    return CodexAppServerHarnessRunner(sandbox_factory=_factory(sandbox), **kwargs)


async def _started(sandbox: _FakeSandbox, **kwargs: Any) -> tuple[CodexAppServerHarnessRunner, str]:
    runner = _runner(sandbox, **kwargs)
    sid = await runner.start_session(_spec(), workdir="/repos/proj")
    return runner, sid


# --- provider surface ---------------------------------------------------------


class TestProviderSurface:
    def test_identity_and_preference(self) -> None:
        runner = _runner(_FakeSandbox())
        assert runner.name == "codex_app_server"
        assert runner.name == PREFERRED_CODEX_PROVIDER
        assert runner.slot == SLOT_NAME
        assert runner.requires() == ("codex-app-server",)

    async def test_healthcheck_reflects_binary_presence(self) -> None:
        healthy = _runner(_FakeSandbox(default=(0, "/usr/bin/codex-app-server")))
        assert (await healthy.healthcheck()).healthy is True
        missing = _runner(_FakeSandbox(default=(1, "")))
        assert (await missing.healthcheck()).healthy is False

    async def test_start_session_correlates_foreign_thread_id(self) -> None:
        sandbox = _FakeSandbox({"codex-app-server session create": _CREATE_OK})
        runner, sid = await _started(sandbox)
        # The maistro session id is the handle; the codex thread id is metadata.
        assert isinstance(sid, str) and len(sid) > 0
        assert runner.foreign_session_id(sid) == "codex-thread-123"
        assert any(cmd.startswith("codex-app-server session create") for cmd in sandbox.commands)

    async def test_send_returns_envelope_with_provider_metadata(self) -> None:
        sandbox = _FakeSandbox(
            {
                "codex-app-server session create": _CREATE_OK,
                "codex-app-server session turn": (
                    0,
                    '{"content": "fixed the bug", "turn_id": "turn-9", '
                    '"actions": [{"tool": "edit", "path": "foo.py"}]}',
                ),
            }
        )
        runner, sid = await _started(sandbox)
        env = await runner.send(sid, [{"role": "user", "content": "fix the bug"}])
        assert env["choices"][0]["message"]["content"] == "fixed the bug"
        assert env["exit_code"] == 0
        assert env["actions"] == [{"tool": "edit", "path": "foo.py"}]
        # Correlation rides as provider metadata only; the maistro session id
        # stays the authoritative handle.
        assert env["provider_metadata"] == {
            "provider": "codex_app_server",
            "session_id": sid,
            "foreign_session_id": "codex-thread-123",
            "foreign_turn_id": "turn-9",
        }
        # The turn ran against the correlated thread, prompt quoted as one arg.
        turn_cmds = [c for c in sandbox.commands if "session turn" in c]
        assert turn_cmds and "--session codex-thread-123" in turn_cmds[0]
        assert "'fix the bug'" in turn_cmds[0]

    async def test_send_excludes_system_messages_and_honors_model(self) -> None:
        sandbox = _FakeSandbox({"codex-app-server session create": _CREATE_OK})
        runner, sid = await _started(sandbox, model="openai/codex")
        await runner.send(
            sid,
            [
                {"role": "system", "content": "SECRET SYSTEM PROMPT"},
                {"role": "user", "content": "go"},
            ],
        )
        turn_cmd = next(c for c in sandbox.commands if "session turn" in c)
        assert "SECRET SYSTEM PROMPT" not in turn_cmd
        assert "--model openai/codex" in turn_cmd

    async def test_send_unknown_or_stopped_session_is_keyerror(self) -> None:
        runner = _runner(_FakeSandbox())
        with pytest.raises(KeyError):
            await runner.send("nope", [{"role": "user", "content": "hi"}])


# --- truthful failure / cancellation projection --------------------------------


class TestTruthfulProjection:
    async def test_failed_session_create_fails_closed_without_half_state(self) -> None:
        sandbox = _FakeSandbox({"codex-app-server session create": (1, "app server boom")})
        with pytest.raises(CodexTurnError, match="session create failed"):
            await _started(sandbox)
        # No half-registered session: the sandbox was released again.
        assert sandbox.destroyed is True

    async def test_raising_session_create_cleans_up_registered_session(self) -> None:
        sandbox = _FakeSandbox(fail_on="codex-app-server session create")  # VM crash
        runner = _runner(sandbox)
        with pytest.raises(RuntimeError, match="vm crashed"):
            await runner.start_session(_spec(), workdir="/repos/proj")
        # The exception path must not orphan the already-registered session:
        # sandbox destroyed, registry empty, no unstopped session left behind.
        assert sandbox.destroyed is True
        assert not runner._sessions

    async def test_session_create_non_object_output_fails_closed(self) -> None:
        # A parseable-but-non-object create result still yields no thread id:
        # fail closed rather than keeping a half-registered session.
        sandbox = _FakeSandbox({"codex-app-server session create": (0, "[1, 2, 3]")})
        with pytest.raises(CodexTurnError, match="session create failed"):
            await _started(sandbox)
        assert sandbox.destroyed is True

    async def test_session_create_without_session_id_fails_closed(self) -> None:
        # A JSON object with no usable session_id is just as unusable as a
        # non-object one: no correlation, no session.
        sandbox = _FakeSandbox({"codex-app-server session create": (0, '{"status": "ok"}')})
        with pytest.raises(CodexTurnError, match="session create failed"):
            await _started(sandbox)
        assert sandbox.destroyed is True

    async def test_create_exec_failure_releases_sandbox_and_propagates(self) -> None:
        # If the create exec itself raises (launcher timeout / VM crash) there
        # is no exit code to read: the orphan sandbox must still be released
        # and the original failure propagated.
        sandbox = _FakeSandbox(fail_on="codex-app-server session create")
        with pytest.raises(RuntimeError, match="vm crashed"):
            await _started(sandbox)
        assert sandbox.destroyed is True

    async def test_session_create_unparseable_output_fails_closed(self) -> None:
        # A non-JSON create response also yields no thread id; fail closed.
        sandbox = _FakeSandbox({"codex-app-server session create": (0, "not json at all")})
        with pytest.raises(CodexTurnError, match="session create failed"):
            await _started(sandbox)
        assert sandbox.destroyed is True

    async def test_failed_turn_raises_instead_of_fabricating_success(self) -> None:
        sandbox = _FakeSandbox(
            {
                "codex-app-server session create": _CREATE_OK,
                "codex-app-server session turn": (3, "segfault"),
            }
        )
        runner, sid = await _started(sandbox)
        with pytest.raises(CodexTurnError, match="turn failed \\(exit 3\\)"):
            await runner.send(sid, [{"role": "user", "content": "hi"}])
        # The correlation survives a failed turn — the thread is still there
        # for recovery/restart; the failure is the caller's to project.
        assert runner.foreign_session_id(sid) == "codex-thread-123"

    async def test_unparseable_turn_result_raises(self) -> None:
        sandbox = _FakeSandbox(
            {
                "codex-app-server session create": _CREATE_OK,
                "codex-app-server session turn": (0, "<html>not json</html>"),
            }
        )
        runner, sid = await _started(sandbox)
        with pytest.raises(CodexTurnError, match="unparseable"):
            await runner.send(sid, [{"role": "user", "content": "hi"}])

    async def test_non_object_turn_result_raises(self) -> None:
        sandbox = _FakeSandbox(
            {
                "codex-app-server session create": _CREATE_OK,
                "codex-app-server session turn": (0, "[1, 2, 3]"),
            }
        )
        runner, sid = await _started(sandbox)
        with pytest.raises(CodexTurnError, match="not an object"):
            await runner.send(sid, [{"role": "user", "content": "hi"}])

    async def test_stop_cleans_up_thread_and_sandbox(self) -> None:
        sandbox = _FakeSandbox({"codex-app-server session create": _CREATE_OK})
        runner, sid = await _started(sandbox)
        await runner.stop(sid)
        assert any("session stop --session codex-thread-123" in c for c in sandbox.commands)
        assert runner.foreign_session_id(sid) is None
        assert sandbox.destroyed is True
        # Cancellation projects truthfully: no further turns are possible and
        # callers get a typed unknown-session error, never a synthetic result.
        with pytest.raises(KeyError):
            await runner.send(sid, [{"role": "user", "content": "after stop"}])

    async def test_stop_is_idempotent_and_survives_foreign_stop_failure(self) -> None:
        sandbox = _FakeSandbox(
            {"codex-app-server session create": _CREATE_OK},
            default=(1, "stop failed"),
        )
        runner, sid = await _started(sandbox)
        await runner.stop(sid)  # foreign stop command fails; teardown continues
        assert sandbox.destroyed is True
        await runner.stop(sid)  # unknown session: no-op, no raise


# --- streaming projection -------------------------------------------------------


class TestStreamProjection:
    async def test_events_project_to_canonical_observation(self) -> None:
        ndjson = "\n".join(
            [
                '{"type": "task_started"}',
                '{"type": "agent_message", "text": "working"}',
                '{"type": "tool_request", "tool": "shell", "argv": ["ls"]}',
                '{"type": "task_complete"}',
            ]
        )
        sandbox = _FakeSandbox(
            {
                "codex-app-server session create": _CREATE_OK,
                "codex-app-server session stream": (0, ndjson),
            }
        )
        runner, sid = await _started(sandbox)
        events = [e async for e in runner.stream(sid)]
        assert events[0]["type"] == "status" and events[0]["state"] == "streaming"
        kinds = [e["type"] for e in events[1:-1]]
        assert kinds == [
            "codex.task_started",
            "codex.agent_message",
            "tool_call",  # effect requests project on the gated seam
            "codex.task_complete",
        ]
        tool_event = events[3]
        assert tool_event["payload"]["tool"] == "shell"
        assert all(e["foreign_session_id"] == "codex-thread-123" for e in events[1:-1])
        assert events[-1]["type"] == "status" and events[-1]["state"] == "ready"

    async def test_unparseable_stream_lines_surface_as_error_events(self) -> None:
        sandbox = _FakeSandbox(
            {
                "codex-app-server session create": _CREATE_OK,
                "codex-app-server session stream": (0, 'garbage\n{"type": "ok"}'),
            }
        )
        runner, sid = await _started(sandbox)
        events = [e async for e in runner.stream(sid)]
        assert any(e["type"] == "error" and "garbage" in e["detail"] for e in events)
        assert events[-1]["state"] == "failed"

    async def test_blank_and_non_object_lines_surface_without_fatal(self) -> None:
        # Blank NDJSON lines are skipped; a non-object line is surfaced as an
        # error event and marks the terminal status failed — never silently
        # reshaped into a successful observation.
        ndjson = '\n{"type": "task_started"}\n[1, 2, 3]\n{"type": "task_complete"}\n'
        sandbox = _FakeSandbox(
            {
                "codex-app-server session create": _CREATE_OK,
                "codex-app-server session stream": (0, ndjson),
            }
        )
        runner, sid = await _started(sandbox)
        events = [e async for e in runner.stream(sid)]
        assert [e["type"] for e in events[1:-1]] == [
            "codex.task_started",
            "error",
            "codex.task_complete",
        ]
        assert any("non-object" in e["detail"] for e in events if e["type"] == "error")
        assert events[-1]["state"] == "failed"

    async def test_failed_stream_exit_projects_failed_status(self) -> None:
        sandbox = _FakeSandbox(
            {
                "codex-app-server session create": _CREATE_OK,
                "codex-app-server session stream": (9, ""),
            }
        )
        runner, sid = await _started(sandbox)
        events = [e async for e in runner.stream(sid)]
        assert events[-1]["state"] == "failed"


# --- microVM wiring (scoped credentials, pointed-at workspace) ------------------


class _FakeLauncher:
    def __init__(self, result: tuple[int, str] = (0, "vm-ran")) -> None:
        self.result = result
        self.specs: list[MicroVMRunSpec] = []

    async def run(self, spec: MicroVMRunSpec) -> tuple[int, str]:
        self.specs.append(spec)
        return self.result


class _ScriptedLauncher:
    """Returns a create-result for `session create`, else the turn result."""

    def __init__(self, turn_result: tuple[int, str]) -> None:
        self.turn_result = turn_result
        self.specs: list[MicroVMRunSpec] = []

    async def run(self, spec: MicroVMRunSpec) -> tuple[int, str]:
        self.specs.append(spec)
        if "session create" in spec.command:
            return (0, '{"session_id": "codex-vm-thread"}')
        return self.turn_result


class TestMicroVMWiring:
    async def test_factory_boots_microvm_at_workdir_with_scoped_env(self) -> None:
        launcher = _FakeLauncher()
        factory = codex_app_server_microvm_factory(launcher, env={"CODEX_MODEL_API_KEY": "k"})
        sandbox = await factory("/repos/target")
        assert isinstance(sandbox, MicroVMSandbox)
        code, out = await sandbox.exec("codex-app-server session create")
        assert code == 0 and out == "vm-ran"
        assert launcher.specs[0].workspace == "/repos/target"
        # Credential scoping: exactly the App Server's own credential material
        # crosses the VM boundary — no broad MAIstro service tokens ride along.
        assert launcher.specs[0].env == {"CODEX_MODEL_API_KEY": "k"}

    async def test_runner_end_to_end_inside_microvm(self) -> None:
        launcher = _ScriptedLauncher((0, '{"content": "vm-turn", "actions": []}'))
        runner = codex_app_server_microvm_runner(launcher, model="openai/codex")
        sid = await runner.start_session(_spec(), workdir="/repos/app")
        env = await runner.send(sid, [{"role": "user", "content": "add tests"}])
        assert env["choices"][0]["message"]["content"] == "vm-turn"
        assert launcher.specs[-1].workspace == "/repos/app"
        assert "--model openai/codex" in launcher.specs[-1].command


# --- governed integration (HarnessSessionManager / canonical effect path) -------


class _StubWarden:
    def __init__(self, block_on: str | None = None) -> None:
        self.block_on = block_on

    async def scan(self, content: str, boundary: str, **_kwargs: Any) -> WardenVerdict:
        if self.block_on is not None and self.block_on in content:
            return WardenVerdict(clean=False, blocked=True, flags=("injection",))
        return WardenVerdict(clean=True)


class _AllowGate:
    async def allow(self, action: dict[str, Any]) -> bool:
        return True


class _DenyGate:
    async def allow(self, action: dict[str, Any]) -> bool:
        return False


def _governed_manager(
    sandbox: _FakeSandbox,
    *,
    warden: _StubWarden | None = None,
    gate: Any = None,
    invocation_store: InMemoryInvocationStore | None = None,
) -> HarnessSessionManager:
    effects = new_effect_context(
        policy_evaluator=binding_scope_policy,
        invocation_store=invocation_store,
    )
    binding = Binding(
        binding_id=f"codex-harness-{id(sandbox)}",
        workspace_id="default",
        project_id="default",
        capability=SLOT_NAME,
        provider_name=PREFERRED_CODEX_PROVIDER,
    )
    effects.bindings.register(binding)
    registry = default_capability_registry(entry_points=[])
    runner = CodexAppServerHarnessRunner(sandbox_factory=_factory(sandbox))
    registry.register(runner)
    registry.activate(SLOT_NAME, PREFERRED_CODEX_PROVIDER)
    return HarnessSessionManager(
        registry,
        warden=warden or _StubWarden(),
        policy=SequencePolicyEngine([]),
        invocation_service=effects.invocations,
        invocation_binding=binding,
        gate_factory=lambda _sid: gate if gate is not None else _AllowGate(),
    )


_CREATE_ACTIONS = (
    0,
    '{"content": "did the thing", "turn_id": "turn-1", '
    '"actions": [{"tool": "shell", "argv": ["git", "push"]}], "exit_code": 0}',
)


class TestGovernedIntegration:
    async def test_full_lifecycle_through_governed_invocation(self) -> None:
        sandbox = _FakeSandbox(
            {
                "codex-app-server session create": _CREATE_OK,
                "codex-app-server session turn": _CREATE_ACTIONS,
            }
        )
        mgr = _governed_manager(sandbox)
        sid = await mgr.start(_spec(), workdir="/repos/proj")
        assert isinstance(sid, str)
        assert mgr.active_sessions() == [sid]

        resp = await mgr.send(sid, [{"role": "user", "content": "do the thing"}])
        assert not isinstance(resp, Unavailable)
        assert resp["choices"][0]["message"]["content"] == "did the thing"
        # Allowed tool requests traverse the gate and stay in the envelope.
        assert resp["actions"] == [{"tool": "shell", "argv": ["git", "push"]}]
        assert resp["provider_metadata"]["provider"] == PREFERRED_CODEX_PROVIDER

        await mgr.stop(sid)
        assert mgr.active_sessions() == []
        assert any("session stop" in c for c in sandbox.commands)

    async def test_denied_effect_is_dropped_before_surfacing(self) -> None:
        sandbox = _FakeSandbox(
            {
                "codex-app-server session create": _CREATE_OK,
                "codex-app-server session turn": _CREATE_ACTIONS,
            }
        )
        mgr = _governed_manager(sandbox, gate=_DenyGate())
        sid = await mgr.start(_spec(), workdir="/repos/proj")
        assert isinstance(sid, str)
        resp = await mgr.send(sid, [{"role": "user", "content": "push it"}])
        assert not isinstance(resp, Unavailable)
        # Sentinel/ActionGate denial: the effect request is dropped; maistro
        # never executes or relays it.
        assert resp["actions"] == []

    async def test_warden_blocks_inbound_before_codex_sees_it(self) -> None:
        sandbox = _FakeSandbox({"codex-app-server session create": _CREATE_OK})
        mgr = _governed_manager(sandbox, warden=_StubWarden(block_on="EVIL"))
        sid = await mgr.start(_spec(), workdir="/repos/proj")
        assert isinstance(sid, str)
        with pytest.raises(HarnessInputBlocked):
            await mgr.send(sid, [{"role": "user", "content": "do EVIL things"}])
        # The untrusted payload never reached the foreign harness.
        assert not any("session turn" in c for c in sandbox.commands)

    async def test_provider_crash_projects_failure(self) -> None:
        sandbox = _FakeSandbox(
            {"codex-app-server session create": _CREATE_OK},
            fail_on="codex-app-server session turn",  # the turn itself crashes
        )
        mgr = _governed_manager(sandbox)
        sid = await mgr.start(_spec(), workdir="/repos/proj")
        assert isinstance(sid, str)
        with pytest.raises(RuntimeError, match="vm crashed"):
            await mgr.send(sid, [{"role": "user", "content": "hi"}])
        # The failed turn is the truth on the wire: no fabricated envelope.

    async def test_unhealthy_provider_degrades_to_unavailable(self) -> None:
        sandbox = _FakeSandbox(default=(1, ""))
        mgr = _governed_manager(sandbox)
        result = await mgr.start(_spec(), workdir="/repos/proj")
        assert isinstance(result, Unavailable)

    async def test_cancellation_projects_as_unknown_session(self) -> None:
        sandbox = _FakeSandbox({"codex-app-server session create": _CREATE_OK})
        mgr = _governed_manager(sandbox)
        sid = await mgr.start(_spec(), workdir="/repos/proj")
        assert isinstance(sid, str)
        await mgr.stop(sid)
        result = await mgr.send(sid, [{"role": "user", "content": "after cancel"}])
        assert isinstance(result, Unavailable)
        assert "unknown harness session" in result.reason

    async def test_governed_turns_record_canonical_execution_identity(self) -> None:
        """Maistro Run/NodeRun/Attempt identity stays authoritative (issue #822).

        Every codex operation traverses an Invocation keyed by maistro's
        canonical identity fields; the codex thread id appears only as
        provider metadata in the response, never as an execution handle.
        """
        store = InMemoryInvocationStore()
        sandbox = _FakeSandbox(
            {
                "codex-app-server session create": _CREATE_OK,
                "codex-app-server session turn": _CREATE_ACTIONS,
            }
        )
        mgr = _governed_manager(sandbox, invocation_store=store)
        sid = await mgr.start(_spec(), workdir="/repos/proj")
        assert isinstance(sid, str)
        await mgr.send(sid, [{"role": "user", "content": "go"}])

        recorded = sorted(store._items.values(), key=lambda i: i.created_at)
        # One governed Invocation per maistro-side operation (start, send).
        assert [invocation.run_id for invocation in recorded] == [
            "harness-start",
            f"harness:{sid}",
        ]
        # The maistro session id is the NodeRun-level handle everywhere; each
        # Invocation carries its own attempt identity.
        assert recorded[0].node_run_id == "harness-start"
        assert recorded[1].node_run_id == sid
        assert all(
            isinstance(invocation.attempt_id, str) and invocation.attempt_id
            for invocation in recorded
        )

    async def test_harness_output_cannot_mint_new_sessions_or_runs(self) -> None:
        """Codex stays a provider, never a peer scheduler (issue #822)."""
        sandbox = _FakeSandbox(
            {
                "codex-app-server session create": _CREATE_OK,
                "codex-app-server session turn": (
                    0,
                    '{"content": "SESSION CREATE new-goal schedule run", '
                    '"actions": [], "exit_code": 0}',
                ),
            }
        )
        mgr = _governed_manager(sandbox)
        sid = await mgr.start(_spec(), workdir="/repos/proj")
        assert isinstance(sid, str)
        resp = await mgr.send(sid, [{"role": "user", "content": "schedule another goal please"}])
        assert not isinstance(resp, Unavailable)
        # Harness-reported text is inert observation: only maistro-side
        # manager.start (a governed, Binding-admitted call) can create
        # sessions — no maistro session, goal, or run was minted from it.
        assert mgr.active_sessions() == [sid]


# --- canonical graph node integration (SPEC-208 §5 outbound) --------------------


class TestGraphNodeIntegration:
    def _executor(self, sandbox: _FakeSandbox) -> HarnessNodeExecutor:
        return HarnessNodeExecutor(_governed_manager(sandbox), workdir="/repos/proj")

    async def test_graph_node_runs_turn_and_stops_session(self) -> None:
        sandbox = _FakeSandbox(
            {
                "codex-app-server session create": _CREATE_OK,
                "codex-app-server session turn": _CREATE_ACTIONS,
            }
        )
        output = await self._executor(sandbox).run(
            role=GraphAgentRole.CODER,
            system_prompt="be a coder",
            user_prompt="fix the bug",
            blackboard=None,
            output_type=HarnessOutput,
        )
        assert isinstance(output, HarnessOutput)
        assert output.summary == "did the thing"
        assert output.actions == [{"tool": "shell", "argv": ["git", "push"]}]
        # The executor stops its own session: no leaked codex threads.
        assert any("session stop" in c for c in sandbox.commands)

    async def test_graph_node_turn_failure_raises_harness_execution_error(self) -> None:
        sandbox = _FakeSandbox(
            {
                "codex-app-server session create": _CREATE_OK,
                "codex-app-server session turn": (2, "app server died"),
            }
        )
        with pytest.raises((HarnessExecutionError, CodexTurnError), match="turn failed"):
            await self._executor(sandbox).run(
                role=GraphAgentRole.CODER,
                system_prompt="s",
                user_prompt="u",
                blackboard=None,
                output_type=HarnessOutput,
            )
        # Failure still releases the session (finally-stop).
        assert any("session stop" in c for c in sandbox.commands)
