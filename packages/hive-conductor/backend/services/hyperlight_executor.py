"""Compatibility code-execution adapter over the canonical sandbox authority.

History, because the shape of this module is the lesson: this used to *be* a
second sandbox authority. It carried its own tier integers, its own backend
probes, and five private launcher implementations (hyperlight, firecracker,
gVisor, bubblewrap, hardened container) while `maistro.sandbox` held the real
protocol, policy ladder and selector. Two authorities meant two opinions about
what "isolated enough" means, and this one's were worse:

- it counted `runsc`-on-PATH as a Tier-2 boundary that
  `docs/security/SANDBOX-SUPPORT-MATRIX.md` explicitly calls "detected, not
  implemented" — a claim the canonical selector refuses to make;
- it passed the host's whole environment through to the sandbox (`dict(os.environ)`
  plus overrides), so ambient credentials rode into every unattended node;
- it kept a private bubblewrap argv, so the flags that ARE the Tier-3 boundary
  existed twice and could drift.

#18 retires the duplicate. Everything policy-shaped now lives behind the one
canonical authority (`maistro.sandbox`, ADR-093): selection is
`SandboxSelector` over `WorkloadPolicy`, egress is an explicit `EgressGrant`
decided before the sandbox exists, backends are the canonical registered
implementations, and this module owns only the legacy dict-shaped result
contract that `legacy_dag_node` and the durable graph runner consume.
`get_executor()` keeps its name and home so those consumers — and the
injection tests that stub it — keep their seams.

What this module still decides, and why it may: the *mapping* from the legacy
`execute_node(...)` signature onto canonical machinery. `mode` becomes an
`ExecutionMode` (unknown modes read as unattended — default deny, ADR-093
decision 6), `allow_network` becomes an explicit host-scoped `EgressGrant`
with a named reason or nothing at all, and `memory_mb`/`timeout_s` become
policy ceilings that `build_config` clamps. The floor decision itself — which
tier unattended work needs, and what happens on a host that cannot provide it
— is not repeated here; `selector.select()` answers it, and a host without a
qualifying backend gets the same fail-closed refusal the selector gives every
other consumer.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

from maistro.sandbox import (
    EgressGrant,
    EgressMode,
    EgressNotEnforceableError,
    ExecResult,
    ExecutionMode,
    NoSuitableBackendError,
    SandboxSelector,
    WorkloadPolicy,
    build_selector,
)
from maistro.sandbox.policy import IsolationTier

logger = logging.getLogger("hive.sandbox")

#: The weakest boundary a legacy node may ever run under. Mode floors decide
#: the rest: unattended execution effective-floors to `gvisor`, which no
#: shipped backend provides yet, so a bubblewrap-only host refuses unattended
#: nodes rather than downgrading them — the same answer every other consumer
#: gets from the same selector.
MIN_TIER: IsolationTier = "bubblewrap"

#: Why a networked legacy node gets the host's namespace. A grant without a
#: reason cannot be constructed, and "the node script calls the configured LLM
#: gateway" is the actual reason — the conductor owns that call, the sandbox
#: merely executes it away from the host filesystem.
LEGACY_NODE_EGRESS_REASON = (
    "legacy DAG node calls the configured LLM gateway from inside its sandbox"
)


def _mode_of(mode: str) -> ExecutionMode:
    """Map the legacy mode string; anything unknown reads as unattended.

    The retired ladder answered `MODE_FLOORS.get(mode, autonomous)` the same
    way: a typo'd or novel mode must not weaken the floor. Default deny.
    """
    try:
        return ExecutionMode(mode)
    except ValueError:
        return ExecutionMode.AUTONOMOUS


def _default_guest_python() -> str:
    """Interpreter path as seen *from inside* the sandbox.

    Backends bind the host's runtime directories read-only; an interpreter
    that lives outside them (a uv toolchain under `$HOME`, say) does not exist
    in the guest, so the system interpreter is the honest default.
    """
    executable = sys.executable
    if executable.startswith(("/usr/", "/bin/", "/sbin/")) and Path(executable).exists():
        return executable
    return "/usr/bin/python3"


def _legacy_result(tier: str, result: ExecResult) -> dict[str, Any]:
    """Map a canonical `ExecResult` onto the legacy dict contract.

    The legacy shape is `{"output", "error", "success", "isolation"}` where
    `error` carried stderr (capped at 500 chars) and `output` the stdout.
    Host-side output bounds (#1197) are the backend's business; this mapping
    only refuses to *lie* about them: a stream the host truncated is named in
    `error` instead of being passed off as complete output.
    """
    if result.timed_out:
        return {
            "output": "",
            "error": "timeout",
            "success": False,
            "isolation": tier,
            "duration_ms": result.duration_ms,
        }
    error = result.stderr[:500]
    if result.output_limit_exceeded:
        error = (f"{error}\n" if error else "") + (
            "output limit exceeded: host policy terminated the sandbox and "
            "truncated captured streams"
        )
    return {
        "output": result.stdout,
        "error": error,
        "success": result.exit_code == 0 and not result.output_limit_exceeded,
        "isolation": tier,
        "duration_ms": result.duration_ms,
    }


class SandboxExecutor:
    """Execute one legacy node script through the canonical selector.

    `selector` is injectable so tests — and a deployment that has already
    probed the host — can pin exactly what this executor may reach. Without
    one, the executor assembles the real selector from what the host
    evidenced, exactly like every other consumer of `build_selector`.
    """

    def __init__(
        self,
        *,
        selector: SandboxSelector | None = None,
        guest_python: str | None = None,
    ) -> None:
        self._selector = selector if selector is not None else build_selector()
        self._guest_python = guest_python or _default_guest_python()

    # ─── capability surface (derived, never claimed) ──────────────────────

    @property
    def available(self) -> bool:
        return self._selector.strongest_tier is not None

    @property
    def backend(self) -> str | None:
        """Strongest registered canonical tier, or `None` when nothing ships."""
        return self._selector.strongest_tier

    #: The retired ladder reported an int here; the canonical tier name is the
    #: same fact without a second numbering to keep in sync.
    tier = backend

    def allows_mode(self, mode: str) -> bool:
        """Whether the canonical selector admits this mode on this host.

        Asked with a deny-egress policy: mode admission is about isolation
        tiers. Egress enforceability is checked again at selection time with
        the real grant, so a `scoped` grant cannot slip past on the strength
        of a pre-check that never saw it.
        """
        try:
            self._selector.select(
                self._policy(mode=mode, allow_network=False, memory_mb=256, timeout_s=120)
            )
        except (NoSuitableBackendError, EgressNotEnforceableError):
            return False
        return True

    # ─── policy mapping ───────────────────────────────────────────────────

    def _policy(
        self,
        *,
        mode: str,
        allow_network: bool,
        memory_mb: int,
        timeout_s: int,
    ) -> WorkloadPolicy:
        grant = (
            EgressGrant(mode=EgressMode.HOST, reason=LEGACY_NODE_EGRESS_REASON)
            if allow_network
            else EgressGrant()
        )
        return WorkloadPolicy(
            min_tier=MIN_TIER,
            network_allowed=allow_network,
            max_memory_mb=memory_mb,
            max_timeout_s=timeout_s,
            reason="legacy DAG node code execution (compatibility adapter)",
            mode=_mode_of(mode),
            # Node scripts are config-shaped, but they execute model-chosen
            # task text and context, so the untrusted mode floors apply.
            untrusted=True,
            egress=grant,
        )

    # ─── execution ────────────────────────────────────────────────────────

    async def execute_node(
        self,
        code: str,
        env: dict[str, str] | None = None,
        timeout_s: int = 120,
        allow_network: bool = False,
        memory_mb: int = 256,
        mode: str = "autonomous",
    ) -> dict[str, Any]:
        """Run `code` under the strongest backend the selector admits.

        The sandbox sees exactly `env` — the legacy caller composes an
        explicit, minimal environment (gateway coordinates, task data) — and
        nothing else: canonical backends start from a cleared environment, so
        the retired behavior of inheriting the host's whole `os.environ` is
        structurally gone, not filtered.
        """
        policy = self._policy(
            mode=mode,
            allow_network=allow_network,
            memory_mb=memory_mb,
            timeout_s=timeout_s,
        )
        try:
            tier, backend = self._selector.select(policy)
        except (NoSuitableBackendError, EgressNotEnforceableError) as exc:
            logger.warning("sandbox_refused mode=%s reason=%s", mode, exc)
            return {
                "output": "",
                "error": f"REFUSED: {exc}",
                "success": False,
                "isolation": "fail-closed",
                "duration_ms": 0,
            }

        config = self._selector.build_config(
            policy,
            memory_mb=memory_mb,
            timeout_s=timeout_s,
            env=dict(env or {}),
        )
        instance = await backend.spawn(config=config)
        try:
            result = await backend.exec(
                instance,
                [self._guest_python, "-c", code],
                timeout_s=config.timeout_s,
            )
        finally:
            await backend.destroy(instance)
        return _legacy_result(tier, result)


# ─── Singleton + public API ───────────────────────────────────────────────────

_executor: SandboxExecutor | None = None


def get_executor() -> SandboxExecutor:
    """The process's executor, assembled on first use.

    Constructed lazily: assembly probes the host (a bubblewrap namespace
    probe, a container runtime `info`), and import-time probing would make
    every test process that imports this module pay for it.
    """
    global _executor
    if _executor is None:
        _executor = SandboxExecutor()
    return _executor


async def execute_in_sandbox(
    code: str,
    env: dict[str, str] | None = None,
    allow_network: bool = False,
    mode: str = "autonomous",
) -> dict[str, Any]:
    """Execute code through the canonical selector, or refuse.

    `mode` is "interactive" (human-supervised) or "autonomous" (unattended);
    the canonical mode floors decide what each requires, and an unknown mode
    reads as unattended.
    """
    return await get_executor().execute_node(code, env=env, allow_network=allow_network, mode=mode)


# Backward compat alias
execute_in_microvm = execute_in_sandbox
