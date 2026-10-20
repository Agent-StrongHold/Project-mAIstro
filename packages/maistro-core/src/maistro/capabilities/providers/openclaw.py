"""``openclaw`` harness_runner provider (SPEC-208 §1-2; issue #1613, M1-D).

Drives `OpenClaw <https://openclaw.ai>`_ (formerly Clawdbot/Moltbot, an
open-source personal agent gateway) as a *foreign harness*: maistro hosts it as
one governed graph node — wrap, don't clone. Each turn is one outbound task
through the OpenClaw gateway agent, executed as a non-interactive
``openclaw agent`` CLI turn inside the injected sandbox at the caller's
workspace. In production the sandbox comes from the canonical
``maistro.sandbox`` selector (#76): the factory registers the injected VMM
launcher seam as a vm-tier backend *behind* the selector, so policy admission,
egress and budgets are the selector's decision, never the caller's; tests
inject a fake launcher (the substrate seam), so the far side can be faked
while the near side stays the real provider seam.

Layering (SPEC-208 §2): this provider owns *process isolation* — OpenClaw runs
inside the VM, contained by the sandbox; its filesystem/network access is what
the sandbox grants, never what the harness would otherwise claim. Warden
(inbound) and the ``ActionGate`` (outbound) are still applied by
``SafeHarnessRunner`` around this provider. The turn's text result is returned
as the OpenAI-shaped response envelope so harness-backed agents flow through
the Conduit and governed Invocation path unchanged.

Wiring — point it at a workspace::

    runner = openclaw_microvm_runner(my_vmm_launcher, agent="personal")
    registry.register(runner)
    registry.activate("harness_runner", "openclaw")
    sid = await manager.start(agent_spec, workdir="/repos/my-project")

Gateway credentials never ride on a harness request: they are operator-wired
into the sandbox's trusted env (``env=``), mirroring Binding policy — no silent
credential copy into the foreign process beyond what the Binding grants.
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

_OPENCLAW_BINARY = "openclaw"


class OpenClawHarnessRunner(SubprocessHarnessRunner):
    """Run each turn as one ``openclaw agent`` task through the gateway.

    ``agent`` maps to OpenClaw's ``--agent`` selection; ``session`` pins an
    existing gateway session so a bounded conversation can continue across
    turns. The gateway URL itself is deployment config carried by the sandbox's
    trusted env, not a per-turn argument — the adapter never copies credentials
    from a request into the foreign process.
    """

    def __init__(
        self,
        *,
        sandbox_factory: SandboxFactory,
        agent: str | None = None,
        session: str | None = None,
        extra_args: Sequence[str] = (),
        timeout: int = 300,
        trust_tier: str = "t2",
    ) -> None:
        super().__init__(
            name="openclaw",
            # base ``command`` template is unused — build_command is overridden —
            # but the parent requires one; keep it representative.
            command="openclaw agent --message {prompt}",
            sandbox_factory=sandbox_factory,
            binary=_OPENCLAW_BINARY,
            timeout=timeout,
            trust_tier=trust_tier,
        )
        self._agent = agent
        self._session = session
        self._extra_args = tuple(extra_args)

    def build_command(self, session: _Session, messages: list[dict[str, str]]) -> str:
        """Render one non-interactive ``openclaw agent`` invocation."""
        prompt = "\n".join(_message_text(m) for m in messages if m.get("role") != "system")
        parts = ["openclaw", "agent", "--message", shlex.quote(prompt)]
        if self._agent:
            parts += ["--agent", shlex.quote(self._agent)]
        if self._session:
            parts += ["--session", shlex.quote(self._session)]
        parts += [shlex.quote(a) for a in self._extra_args]
        return " ".join(parts)


def openclaw_microvm_factory(
    launcher: VMMLauncher | LauncherFn,
    *,
    config: MicroVMConfig | None = None,
    env: dict[str, str] | None = None,
    policy: WorkloadPolicy | None = None,
) -> SandboxFactory:
    """A ``SandboxFactory`` whose sandbox comes from the canonical selector.

    The ``workdir`` passed to ``start_session`` becomes the VM's workspace —
    the checkout OpenClaw's gateway agent acts on. ``launcher`` is the VMM
    *substrate* seam (real in prod, fake in tests); it is registered behind a
    ``SandboxSelector`` as the vm-tier backend, and the policy — not the
    caller — decides whether the workload may run (``UNTRUSTED_CODE`` by
    default: a foreign harness executes model-generated code, unattended).
    ``env`` carries OpenClaw's gateway credentials into the VM as
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


def openclaw_microvm_runner(
    launcher: VMMLauncher | LauncherFn,
    *,
    agent: str | None = None,
    session: str | None = None,
    config: MicroVMConfig | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 300,
    policy: WorkloadPolicy | None = None,
) -> OpenClawHarnessRunner:
    """Convenience: an :class:`OpenClawHarnessRunner` backed by a selector-chosen microVM."""
    return OpenClawHarnessRunner(
        sandbox_factory=openclaw_microvm_factory(launcher, config=config, env=env, policy=policy),
        agent=agent,
        session=session,
        timeout=timeout,
    )


__all__ = [
    "OpenClawHarnessRunner",
    "openclaw_microvm_factory",
    "openclaw_microvm_runner",
]
