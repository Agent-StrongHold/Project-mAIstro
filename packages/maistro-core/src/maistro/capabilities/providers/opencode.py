"""``opencode`` harness_runner provider (SPEC-208 §1-2).

Drives `opencode <https://opencode.ai>`_ (``sst/opencode``, an open-source
terminal coding agent) as a foreign harness. Each turn is a non-interactive
``opencode run`` executed inside the injected sandbox, pointed at the caller's
repo/workdir — so opencode edits a real checkout under OS isolation. In
production the sandbox is a :class:`~maistro.tools.sandbox.microvm.MicroVMSandbox`
(own kernel, default-deny network, capped mem/vCPU); tests inject a fake.

Layering (SPEC-208 §2): this provider owns *process isolation* — opencode runs
its own tools ``--auto`` entirely inside the VM, contained by the sandbox. The
turn's text result is returned as the response envelope; Warden (inbound) and the
``ActionGate`` (outbound, on anything maistro relays) are still applied by
``SafeHarnessRunner`` around this provider.

Wiring — point it at a repo::

    runner = opencode_microvm_runner(my_vmm_launcher, model="anthropic/claude-opus-4-8")
    registry.register(runner)
    registry.activate("harness_runner", "opencode")
    sid = await manager.start(agent_spec, workdir="/repos/my-project")  # the repo
"""

from __future__ import annotations

import shlex
from collections.abc import Sequence
from typing import Any

from maistro.capabilities.providers.subprocess_harness import (
    SandboxExec,
    SandboxFactory,
    SubprocessHarnessRunner,
    _message_text,
    _Session,
)
from maistro.tools.sandbox.microvm import (
    LauncherFn,
    MicroVMConfig,
    MicroVMSandbox,
    VMMLauncher,
)

_OPENCODE_BINARY = "opencode"


class OpencodeHarnessRunner(SubprocessHarnessRunner):
    """Run each turn as ``opencode run`` inside a sandboxed checkout.

    ``model`` (``provider/model``) and ``agent`` map to opencode's ``--model`` /
    ``--agent`` flags; ``--auto`` auto-approves opencode's in-VM tool use so the
    turn is non-interactive. Cross-turn conversation continuity (``--continue`` /
    ``--session``) is a v1 enhancement — v0 relies on the repo filesystem as the
    shared state across turns, which is what a coding harness actually mutates.
    """

    def __init__(
        self,
        *,
        sandbox_factory: SandboxFactory,
        model: str | None = None,
        agent: str | None = None,
        extra_args: Sequence[str] = (),
        timeout: int = 300,
        trust_tier: str = "t2",
    ) -> None:
        super().__init__(
            name="opencode",
            # base ``command`` template is unused — build_command is overridden —
            # but the parent requires one; keep it representative.
            command="opencode run {prompt}",
            sandbox_factory=sandbox_factory,
            binary=_OPENCODE_BINARY,
            timeout=timeout,
            trust_tier=trust_tier,
        )
        self._model = model
        self._agent = agent
        self._extra_args = tuple(extra_args)

    def build_command(self, session: _Session, messages: list[dict[str, Any]]) -> str:
        """Render a non-interactive ``opencode run`` invocation for one turn."""
        prompt = "\n".join(_message_text(m) for m in messages if m.get("role") != "system")
        parts = ["opencode", "run", "--auto"]
        if self._model:
            parts += ["--model", shlex.quote(self._model)]
        if self._agent:
            parts += ["--agent", shlex.quote(self._agent)]
        parts += [shlex.quote(a) for a in self._extra_args]
        parts.append(shlex.quote(prompt))
        return " ".join(parts)


def opencode_microvm_factory(
    launcher: VMMLauncher | LauncherFn,
    *,
    config: MicroVMConfig | None = None,
    env: dict[str, str] | None = None,
) -> SandboxFactory:
    """A ``SandboxFactory`` that boots a :class:`MicroVMSandbox` at each workdir.

    The ``workdir`` passed to ``start_session`` becomes the VM's workspace — i.e.
    the repo you point opencode at. ``launcher`` is the VMM seam (real in prod,
    fake in tests); ``env`` carries opencode's provider credentials into the VM.
    """
    shared_env = dict(env or {})

    async def factory(workdir: str) -> SandboxExec:
        # trusted_env, not env: these are opencode's provider credentials, wired
        # in by the operator rather than derived from a harness request, and the
        # sandbox's allowlist would otherwise (correctly) strip them.
        return MicroVMSandbox(launcher, config=config, workspace=workdir, trusted_env=shared_env)

    return factory


def opencode_microvm_runner(
    launcher: VMMLauncher | LauncherFn,
    *,
    model: str | None = None,
    agent: str | None = None,
    config: MicroVMConfig | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 300,
) -> OpencodeHarnessRunner:
    """Convenience: an :class:`OpencodeHarnessRunner` backed by a microVM sandbox."""
    return OpencodeHarnessRunner(
        sandbox_factory=opencode_microvm_factory(launcher, config=config, env=env),
        model=model,
        agent=agent,
        timeout=timeout,
    )


__all__ = [
    "OpencodeHarnessRunner",
    "opencode_microvm_factory",
    "opencode_microvm_runner",
]
