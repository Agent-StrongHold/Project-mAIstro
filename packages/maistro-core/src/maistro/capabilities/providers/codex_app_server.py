"""``codex_app_server`` harness_runner provider (issue #822; SPEC-208 §1-2).

Adapts the Codex App Server — Codex's headless JSON-RPC session/turn API — as
the *preferred* MAIstro foreign-harness provider for Codex execution. It rides
the ordinary ``harness_runner`` slot, so a Codex thread stays exactly what the
issue scopes it as: foreign-harness runtime state, correlated to — never
authoritative over — MAIstro's ``Run/NodeRun/Attempt`` identity, and never a
peer scheduler of the Workspace-Agent reconciler.

Transport: the provider is an adapter over an injected
:class:`~maistro.capabilities.providers.subprocess_harness.SandboxExec` seam
(production: :class:`~maistro.tools.sandbox.microvm.MicroVMSandbox`; tests: a
fake), invoking the App Server bridge binary per operation:

- ``codex-app-server session create``            → ``{"session_id": "..."}``
- ``codex-app-server session turn ...``          → one JSON result envelope
- ``codex-app-server session stream --session …`` → NDJSON event lines
- ``codex-app-server session stop --session …``   → tears the thread down

The bridge command surface is deployment-specific (the App Server speaks
JSON-RPC over stdio; the sandbox-side bridge shapes it into one command per
operation) — the governed boundary MAIstro enforces is provider-side and does
not move with it.

Layering (SPEC-208 §2): this provider owns *process isolation* — every App
Server operation runs inside the injected sandbox. Warden (inbound scan) and
the ``ActionGate`` (outbound, on every reported action/tool request) are
applied by ``SafeHarnessRunner`` / ``HarnessSessionManager`` around this
provider, and turns traverse the canonical ``Binding -> policy -> Invocation``
seam — the App Server is never a second execution authority.

Governance invariants implemented here (issue #822 acceptance):

- **Identity correlation.** ``start_session`` returns the MAIstro session id;
  the foreign App Server session/thread id is kept as provider metadata
  (``foreign_session_id`` accessor and the response envelope's
  ``provider_metadata``), never as an alternate execution handle.
- **Truthful projection.** A failed or unparseable turn raises
  :class:`CodexTurnError` instead of fabricating a successful envelope, so the
  governing Invocation records a failed attempt and the owning NodeRun
  projects the failure through its retry/circuit plumbing. Cancellation is
  ``stop()``: after it, further ``send``/``stream`` raise ``KeyError`` — the
  manager surfaces the typed ``Unavailable`` — never a synthetic result.
- **Disposable foreign state.** ``stop`` always releases MAIstro-side
  resources (sandbox teardown) even when the foreign stop command fails: a
  Codex thread is disposable runtime state, recoverable by starting a new
  session, and cannot become a second durable store.
- **Scoped credentials.** The microVM wiring carries only the App Server's own
  credential material into the sandbox — never MAIstro service tokens or other
  capability credentials; harness-requested external effects ride the gated
  action path instead.

Wiring — point it at a workspace::

    runner = codex_app_server_microvm_runner(my_vmm_launcher, model="openai/codex")
    registry.register(runner)
    registry.activate("harness_runner", "codex_app_server")
    sid = await manager.start(agent_spec, workdir="/repos/my-project")
"""

from __future__ import annotations

import contextlib
import json
import shlex
from collections.abc import AsyncIterator
from typing import Any

from maistro.agents.spec.agent_spec import AgentSpec
from maistro.capabilities.providers.subprocess_harness import (
    SandboxExec,
    SandboxFactory,
    SubprocessHarnessRunner,
    _message_text,
)
from maistro.tools.sandbox.microvm import (
    LauncherFn,
    MicroVMConfig,
    MicroVMSandbox,
    VMMLauncher,
)

CODEX_APP_SERVER_BINARY = "codex-app-server"

# The App Server adapter is the preferred Codex provider (issue #822 support
# matrix, docs/security/HARNESS-SUPPORT-MATRIX.md); any CLI adapter is a
# compatibility/fallback tier and must advertise reduced capabilities.
PREFERRED_CODEX_PROVIDER = "codex_app_server"

# Stream-event kinds the App Server uses to request an external effect. They
# project as ``tool_call`` so SafeHarnessRunner's ActionGate filters them on
# the same seam as every other harness (SPEC-208 §2: gate every action).
_TOOL_EVENT_KINDS = frozenset({"action", "tool_call", "tool_request"})


class CodexTurnError(RuntimeError):
    """A Codex App Server operation failed or returned an unparseable result.

    Raised instead of fabricating a successful envelope: the governed
    Invocation records a failed attempt for the owning NodeRun/Attempt, and
    the typed error propagates to the graph node so its normal
    retry/circuit-breaker plumbing classifies the failure.
    """


class CodexAppServerHarnessRunner(SubprocessHarnessRunner):
    """Drive the Codex App Server's session/turn API inside a sandbox.

    ``start_session`` creates an App Server session (thread) inside the
    session's sandbox and correlates it to the returned MAIstro session id.
    Each ``send`` performs one App Server turn; ``stream`` projects App Server
    NDJSON events into canonical observation events; ``stop`` tears the
    foreign thread and the sandbox down.
    """

    def __init__(
        self,
        *,
        sandbox_factory: SandboxFactory,
        model: str | None = None,
        timeout: int = 300,
        trust_tier: str = "t2",
    ) -> None:
        super().__init__(
            name=PREFERRED_CODEX_PROVIDER,
            # Base ``command`` template is unused — send()/stream() build the
            # per-operation command from the correlated foreign thread id —
            # but the parent requires one; keep it representative.
            command=(
                f"{CODEX_APP_SERVER_BINARY} session turn "
                "--session {session_id} --prompt {prompt}"
            ),
            sandbox_factory=sandbox_factory,
            binary=CODEX_APP_SERVER_BINARY,
            timeout=timeout,
            trust_tier=trust_tier,
        )
        self._model = model
        # MAIstro session id -> foreign App Server session/thread id. This is
        # correlation metadata for observation and support, never a second
        # execution identity: all HarnessRunner operations key on the MAIstro
        # session id.
        self._threads: dict[str, str] = {}

    # --- correlation (foreign thread id as provider metadata) ---

    def foreign_session_id(self, session_id: str) -> str | None:
        """The App Server session/thread id correlated to a MAIstro session."""
        return self._threads.get(session_id)

    # --- HarnessRunner ---

    async def start_session(self, agent_spec: AgentSpec, *, workdir: str) -> str:
        """Create the sandbox + App Server thread; return the MAIstro session id."""
        session_id = await super().start_session(agent_spec, workdir=workdir)
        session = self._require_session(session_id)
        try:
            code, output = await session.sandbox.exec(
                f"{CODEX_APP_SERVER_BINARY} session create", self._timeout
            )
        except BaseException:
            # The exec itself raised (launcher timeout, VM crash, ...): no
            # exit code or response comes back, so the fail-closed branch
            # below never runs. The session is already registered in
            # _sessions but its id has not reached the caller, so nobody can
            # stop this orphan — release the sandbox and registry entry
            # before propagating the original failure.
            await super().stop(session_id)
            raise
        thread_id = self._parse_thread_id(output) if code == 0 else None
        if thread_id is None:
            # Fail closed: never keep a MAIstro session whose foreign thread
            # was not created — the sandbox is released and the caller sees a
            # typed failure instead of a half-registered session.
            await super().stop(session_id)
            raise CodexTurnError(
                f"codex app-server session create failed (exit {code}): {output.strip()[:200]}"
            )
        self._threads[session_id] = thread_id
        return session_id

    async def send(self, session_id: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
        session = self._require_session(session_id)
        thread_id = self.foreign_session_id(session_id)
        if thread_id is None:
            raise KeyError(f"no correlated codex thread for session: {session_id}")
        prompt = "\n".join(_message_text(m) for m in messages if m.get("role") != "system")
        command = self._turn_command(thread_id, prompt)
        code, output = await session.sandbox.exec(command, self._timeout)
        if code != 0:
            raise CodexTurnError(
                f"codex app-server turn failed (exit {code}): {output.strip()[:200]}"
            )
        result = self._parse_turn_result(output)
        actions = [a for a in result.get("actions", []) if isinstance(a, dict)]
        turn_id = result.get("turn_id")
        metadata: dict[str, Any] = {
            "provider": self.name,
            "session_id": session_id,
            "foreign_session_id": thread_id,
        }
        if isinstance(turn_id, str) and turn_id:
            metadata["foreign_turn_id"] = turn_id
        return {
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": result.get("content", "")},
                    "finish_reason": "stop",
                }
            ],
            "exit_code": code,
            "actions": actions,
            # The foreign thread/turn ids ride ONLY as provider metadata; the
            # MAIstro session id stays the authoritative handle (issue #822).
            "provider_metadata": metadata,
        }

    async def stream(self, session_id: str) -> AsyncIterator[dict[str, Any]]:
        """Project App Server stream events into canonical observation events.

        NDJSON lines from the App Server bridge are re-emitted as typed events
        (``codex.<kind>``, or ``tool_call`` for external-effect requests so the
        ActionGate sees them). Unparseable lines are surfaced as ``error``
        events — never dropped or reshaped into success. Note the SandboxExec
        seam buffers the bridge's output; per-line incremental transport is a
        future enhancement (the governing manager buffers streams anyway).
        """
        session = self._require_session(session_id)
        thread_id = self.foreign_session_id(session_id)
        if thread_id is None:
            raise KeyError(f"no correlated codex thread for session: {session_id}")
        code, output = await session.sandbox.exec(self._stream_command(thread_id), self._timeout)
        yield {
            "type": "status",
            "session_id": session_id,
            "state": "streaming",
            "foreign_session_id": thread_id,
        }
        failed = code != 0
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                failed = True
                yield {
                    "type": "error",
                    "session_id": session_id,
                    "detail": f"unparseable codex event: {line[:120]}",
                }
                continue
            if not isinstance(event, dict):
                failed = True
                yield {
                    "type": "error",
                    "session_id": session_id,
                    "detail": f"non-object codex event: {line[:120]}",
                }
                continue
            yield self._project_event(session_id, thread_id, event)
        yield {
            "type": "status",
            "session_id": session_id,
            "state": "failed" if failed else "ready",
        }

    async def stop(self, session_id: str) -> None:
        """Stop the foreign thread and release the sandbox.

        Idempotent: stopping an unknown session is a no-op. A failing foreign
        stop command never leaks MAIstro-side resources — the App Server thread
        is disposable runtime state, so teardown always continues to the
        sandbox release.
        """
        session = self._sessions.get(session_id)
        if session is None:
            return
        thread_id = self._threads.pop(session_id, None)
        if thread_id is not None:
            # The foreign thread is disposable; teardown must not be blocked on
            # it (e.g. sandbox already crashed mid-turn).
            with contextlib.suppress(Exception):
                await session.sandbox.exec(self._stop_command(thread_id), self._timeout)
        await super().stop(session_id)

    # --- internals ---

    def _turn_command(self, thread_id: str, prompt: str) -> str:
        parts = [
            CODEX_APP_SERVER_BINARY,
            "session",
            "turn",
            "--session",
            shlex.quote(thread_id),
            "--prompt",
            shlex.quote(prompt),
        ]
        if self._model:
            parts += ["--model", shlex.quote(self._model)]
        return " ".join(parts)

    def _stream_command(self, thread_id: str) -> str:
        return f"{CODEX_APP_SERVER_BINARY} session stream --session {shlex.quote(thread_id)}"

    def _stop_command(self, thread_id: str) -> str:
        return f"{CODEX_APP_SERVER_BINARY} session stop --session {shlex.quote(thread_id)}"

    @staticmethod
    def _parse_thread_id(output: str) -> str | None:
        try:
            result = json.loads(output.strip())
        except json.JSONDecodeError:
            return None
        if isinstance(result, dict):
            thread_id = result.get("session_id")
            if isinstance(thread_id, str) and thread_id:
                return thread_id
        return None

    @staticmethod
    def _parse_turn_result(output: str) -> dict[str, Any]:
        try:
            result = json.loads(output.strip())
        except json.JSONDecodeError as exc:
            raise CodexTurnError(
                f"unparseable codex app-server turn result: {output.strip()[:200]}"
            ) from exc
        if not isinstance(result, dict):
            raise CodexTurnError(
                f"codex app-server turn result is not an object: {output.strip()[:200]}"
            )
        return result

    @staticmethod
    def _project_event(session_id: str, thread_id: str, event: dict[str, Any]) -> dict[str, Any]:
        kind = event.get("type") or event.get("method") or "event"
        projected: dict[str, Any] = {
            "type": "tool_call" if kind in _TOOL_EVENT_KINDS else f"codex.{kind}",
            "session_id": session_id,
            "foreign_session_id": thread_id,
        }
        payload = {k: v for k, v in event.items() if k not in ("type", "method")}
        if payload:
            projected["payload"] = payload
        return projected


def codex_app_server_microvm_factory(
    launcher: VMMLauncher | LauncherFn,
    *,
    config: MicroVMConfig | None = None,
    env: dict[str, str] | None = None,
) -> SandboxFactory:
    """A ``SandboxFactory`` that boots a :class:`MicroVMSandbox` at each workdir.

    The ``workdir`` passed to ``start_session`` becomes the VM's workspace —
    the repo the Codex App Server operates on. ``launcher`` is the VMM seam
    (real in prod, fake in tests). ``env`` carries ONLY the App Server's own
    scoped credential material (e.g. its model-provider key) into the VM:
    broad MAIstro service tokens, source-control tokens, or other capability
    credentials must not be injected — Codex reaches external effects through
    the gated typed-capability path, not by holding MAIstro's authorities
    (issue #822).
    """
    scoped_env = dict(env or {})

    async def factory(workdir: str) -> SandboxExec:
        # trusted_env, not env: these are the App Server's own provider
        # credentials, wired in by the operator rather than derived from a
        # harness request, and the sandbox's allowlist would otherwise
        # (correctly) strip them.
        return MicroVMSandbox(launcher, config=config, workspace=workdir, trusted_env=scoped_env)

    return factory


def codex_app_server_microvm_runner(
    launcher: VMMLauncher | LauncherFn,
    *,
    model: str | None = None,
    config: MicroVMConfig | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 300,
) -> CodexAppServerHarnessRunner:
    """Convenience: a :class:`CodexAppServerHarnessRunner` backed by a microVM."""
    return CodexAppServerHarnessRunner(
        sandbox_factory=codex_app_server_microvm_factory(launcher, config=config, env=env),
        model=model,
        timeout=timeout,
    )


__all__ = [
    "CODEX_APP_SERVER_BINARY",
    "PREFERRED_CODEX_PROVIDER",
    "CodexAppServerHarnessRunner",
    "CodexTurnError",
    "codex_app_server_microvm_factory",
    "codex_app_server_microvm_runner",
]
