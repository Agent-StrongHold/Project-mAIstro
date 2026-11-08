"""``pi`` harness_runner provider (SPEC-208 §1-2; issue #1613, M1-D).

Drives the `Pi <https://github.com/badlogic/pi-mono>`_ coding agent as a
*foreign harness*: one coding-agent turn in print (non-interactive) mode,
executed inside the injected sandbox at the caller's workspace — maistro hosts
Pi, it does not become Pi and Pi does not become the execution runtime. In
production the sandbox comes from the canonical ``maistro.sandbox`` selector
(#76): the factory registers the injected VMM launcher seam as a vm-tier
backend *behind* the selector, so policy admission, egress and budgets are the
selector's decision, never the caller's; tests inject a fake launcher (the
substrate seam), so the far side can be faked while the near side stays the
real provider seam.

Layering (SPEC-208 §2): this provider owns *process isolation* — Pi runs its
own agent loop and tools entirely inside the VM, contained by the sandbox.
Warden (inbound) and the ``ActionGate`` (outbound, on anything maistro relays)
are still applied by ``SafeHarnessRunner`` around this provider. The turn's
text result is returned as the OpenAI-shaped response envelope so
harness-backed agents flow through the Conduit and governed Invocation path
unchanged.

Wiring — point it at a repo::

    runner = pi_microvm_runner(my_vmm_launcher, model="anthropic/claude-opus-4-8")
    registry.register(runner)
    registry.activate("harness_runner", "pi")
    sid = await manager.start(agent_spec, workdir="/repos/my-project")  # the repo

Pi's provider credentials never ride on a harness request: they are
operator-wired into the sandbox's trusted env (``env=``), mirroring Binding
policy — no silent credential copy into the foreign process.
"""

from __future__ import annotations

import shlex
from collections.abc import Sequence
from typing import TYPE_CHECKING

from maistro.capabilities.providers.subprocess_harness import (
    SandboxExec,
    SandboxFactory,
    SelectorSandboxExec,
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
    # Behind ``maistro.sandbox``'s package init (which imports the runs/graph
    # chain back into ``maistro.capabilities``): type-checker-only here (#76).
    from maistro.sandbox.policy import WorkloadPolicy

_PI_BINARY = "pi"


class PiHarnessRunner(SubprocessHarnessRunner):
    """Run each turn as one ``pi -p`` print-mode coding-agent turn.

    ``model`` (``provider/model``) and ``provider`` map to Pi's ``--model`` /
    ``--provider`` flags; ``-p`` keeps the turn non-interactive so the graph
    node's send() is one bounded RPC-shaped turn rather than a TUI session.
    Cross-turn continuity relies on the shared workspace filesystem, which is
    what a coding harness actually mutates; pinning Pi's own session id across
    turns is a v1 enhancement.
    """

    def __init__(
        self,
        *,
        sandbox_factory: SandboxFactory,
        model: str | None = None,
        provider: str | None = None,
        extra_args: Sequence[str] = (),
        timeout: int = 300,
        trust_tier: str = "t2",
    ) -> None:
        super().__init__(
            name="pi",
            # base ``command`` template is unused — build_command is overridden —
            # but the parent requires one; keep it representative.
            command="pi -p {prompt}",
            sandbox_factory=sandbox_factory,
            binary=_PI_BINARY,
            timeout=timeout,
            trust_tier=trust_tier,
        )
        self._model = model
        self._provider = provider
        self._extra_args = tuple(extra_args)

    def build_command(self, session: _Session, messages: list[dict[str, str]]) -> str:
        """Render one non-interactive ``pi -p`` invocation for one turn."""
        prompt = "\n".join(_message_text(m) for m in messages if m.get("role") != "system")
        parts = ["pi", "-p"]
        if self._provider:
            parts += ["--provider", shlex.quote(self._provider)]
        if self._model:
            parts += ["--model", shlex.quote(self._model)]
        parts += [shlex.quote(a) for a in self._extra_args]
        parts.append(shlex.quote(prompt))
        return " ".join(parts)


def pi_microvm_factory(
    launcher: VMMLauncher | LauncherFn,
    *,
    config: MicroVMConfig | None = None,
    env: dict[str, str] | None = None,
    policy: WorkloadPolicy | None = None,
) -> SandboxFactory:
    """A ``SandboxFactory`` whose sandbox comes from the canonical selector.

    The ``workdir`` passed to ``start_session`` becomes the VM's workspace —
    the repo you point Pi at. ``launcher`` is the VMM *substrate* seam (real in
    prod, fake in tests); it is registered behind a ``SandboxSelector`` as the
    vm-tier backend, and the policy — not the caller — decides whether the
    workload may run (``UNTRUSTED_CODE`` by default: a foreign harness executes
    model-generated code, unattended). ``env`` carries Pi's provider
    credentials into the VM as operator-trusted env (see ``MicroVMSandbox`` for
    that channel's contract).
    """
    shared_env = dict(env or {})
    # The canonical authority imports live here (see the TYPE_CHECKING note):
    # at module load they would be circular; at factory-call time every
    # package is initialized.
    from maistro.sandbox.policy import UNTRUSTED_CODE
    from maistro.sandbox.wiring import build_launcher_selector

    effective_policy = policy if policy is not None else UNTRUSTED_CODE

    async def factory(workdir: str) -> SandboxExec:
        selector = build_launcher_selector(
            launcher, config=config, workspace=workdir, trusted_env=shared_env
        )
        _tier, backend = selector.select(effective_policy)
        instance = await backend.spawn(config=selector.build_config(effective_policy))
        return SelectorSandboxExec(backend, instance)

    return factory


def pi_microvm_runner(
    launcher: VMMLauncher | LauncherFn,
    *,
    model: str | None = None,
    provider: str | None = None,
    config: MicroVMConfig | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 300,
    policy: WorkloadPolicy | None = None,
) -> PiHarnessRunner:
    """Convenience: a :class:`PiHarnessRunner` backed by a selector-chosen microVM."""
    return PiHarnessRunner(
        sandbox_factory=pi_microvm_factory(launcher, config=config, env=env, policy=policy),
        model=model,
        provider=provider,
        timeout=timeout,
    )


__all__ = [
    "PiHarnessRunner",
    "pi_microvm_factory",
    "pi_microvm_runner",
]
