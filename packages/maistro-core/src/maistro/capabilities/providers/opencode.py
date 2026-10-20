"""``opencode`` harness_runner provider (SPEC-208 §1-2).

Drives `opencode <https://opencode.ai>`_ (``sst/opencode``, an open-source
terminal coding agent) as a foreign harness. Each turn is a non-interactive
``opencode run`` executed inside the injected sandbox, pointed at the caller's
repo/workdir — so opencode edits a real checkout under OS isolation. The
production sandbox comes from the canonical ``maistro.sandbox`` selector
(#76): the factory below registers the injected VMM launcher seam as a
vm-tier backend *behind* the selector, so policy admission, egress and
budgets are the selector's decision, never the caller's. Tests inject a fake
launcher (the substrate seam); the authority does not change.

Layering (SPEC-208 §2): this provider owns *process isolation* — opencode runs
its own tools ``--auto`` entirely inside the sandbox, contained by the sandbox.
The turn's text result is returned as the response envelope; Warden (inbound)
and the ``ActionGate`` (outbound, on anything maistro relays) are still applied
by ``SafeHarnessRunner`` around this provider.

Wiring — point it at a repo::

    runner = opencode_microvm_runner(my_vmm_launcher, model="anthropic/claude-opus-4-8")
    registry.register(runner)
    registry.activate("harness_runner", "opencode")
    sid = await manager.start(agent_spec, workdir="/repos/my-project")  # the repo
"""

from __future__ import annotations

import shlex
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

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
    VMMLauncher,
)

if TYPE_CHECKING:
    # Imported lazily at call time, not here: these modules sit behind
    # ``maistro.sandbox``'s package init, which imports the runs/graph chain
    # back into ``maistro.capabilities`` — importing them while this module
    # loads would be circular.
    from maistro.sandbox.policy import WorkloadPolicy
    from maistro.sandbox.protocol import SandboxInstance, SandboxProtocol

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


class SelectorSandboxExec:
    """``SandboxExec`` view of one selector-selected sandbox instance (#76).

    Every turn executes through the selected canonical backend; there is no
    second, provider-private sandbox implementation to bypass policy with.
    """

    def __init__(self, backend: SandboxProtocol, instance: SandboxInstance) -> None:
        self._backend = backend
        self._instance = instance

    async def exec(self, command: str, timeout: int = 60) -> tuple[int, str]:
        # One element = the shell command line, handed to the backend verbatim
        # (the ``LauncherVMSandboxBackend`` contract); the backend's own
        # dangerous-command screen sees exactly what the harness asked for.
        result = await self._backend.exec(self._instance, [command], timeout_s=timeout)
        return result.exit_code, result.stdout + result.stderr


def opencode_microvm_factory(
    launcher: VMMLauncher | LauncherFn,
    *,
    config: MicroVMConfig | None = None,
    env: dict[str, str] | None = None,
    policy: WorkloadPolicy | None = None,
) -> SandboxFactory:
    """A ``SandboxFactory`` whose sandbox comes from the canonical selector.

    The ``workdir`` passed to ``start_session`` becomes the VM's workspace —
    i.e. the repo you point opencode at. ``launcher`` is the VMM *substrate*
    seam (real in prod, fake in tests); it is registered behind a
    ``SandboxSelector`` as the vm-tier backend, and the policy — not the
    caller — decides whether the workload may run (``UNTRUSTED_CODE`` by
    default: a foreign harness executes model-generated code, unattended).
    ``env`` carries opencode's provider credentials into the VM as
    operator-trusted env (see ``MicroVMSandbox`` for that channel's contract).
    """
    shared_env = dict(env or {})
    # The canonical authority imports live here (see the TYPE_CHECKING note):
    # at module load they would be circular; at factory-call time every
    # package is initialized.
    from maistro.sandbox.backends.launcher_vm import LauncherVMSandboxBackend
    from maistro.sandbox.policy import UNTRUSTED_CODE
    from maistro.sandbox.selector import SandboxSelector

    effective_policy = policy if policy is not None else UNTRUSTED_CODE

    async def factory(workdir: str) -> SandboxExec:
        selector = SandboxSelector()
        selector.register(
            "vm",
            LauncherVMSandboxBackend(
                launcher, config=config, workspace=workdir, trusted_env=shared_env
            ),
        )
        _tier, backend = selector.select(effective_policy)
        instance = await backend.spawn(config=selector.build_config(effective_policy))
        return SelectorSandboxExec(backend, instance)

    return factory


def opencode_microvm_runner(
    launcher: VMMLauncher | LauncherFn,
    *,
    model: str | None = None,
    agent: str | None = None,
    extra_args: Sequence[str] = (),
    timeout: int = 300,
    config: MicroVMConfig | None = None,
    env: dict[str, str] | None = None,
    policy: WorkloadPolicy | None = None,
) -> OpencodeHarnessRunner:
    """Convenience constructor: the canonical-selector factory wired in."""
    return OpencodeHarnessRunner(
        sandbox_factory=opencode_microvm_factory(launcher, config=config, env=env, policy=policy),
        model=model,
        agent=agent,
        extra_args=extra_args,
        timeout=timeout,
    )


__all__ = [
    "OpencodeHarnessRunner",
    "SelectorSandboxExec",
    "opencode_microvm_factory",
    "opencode_microvm_runner",
]
