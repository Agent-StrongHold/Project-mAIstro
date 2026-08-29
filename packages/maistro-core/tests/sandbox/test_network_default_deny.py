"""Unattended sandboxes get no network, and grants are explicit (#77).

The distinction this suite rests on: `maistro.security.ssrf` guards the
engine's *own* outbound calls, and is worth nothing against candidate code,
which is not obliged to go through Python at all. A model-authored script can
open a socket. So "no network" has to mean the kernel never gave the sandbox an
interface — which is a claim about a namespace, and is checked here against the
namespace rather than against a Python function.

The other half is honesty about enforcement. Bubblewrap has two network states:
an empty namespace, or the host's shared whole. It cannot permit one
destination and refuse another, so a scoped grant must be **refused** rather
than approximated — an implementation that read "scoped" as "on" would hand
over unrestricted egress while the audit line said "scoped".
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from maistro.sandbox import (
    BROWSER_AUTOMATION,
    TRUSTED_TOOL,
    UNTRUSTED_CODE,
    NoSuitableBackendError,
    SandboxConfig,
    SandboxSelector,
)
from maistro.sandbox.backends.bubblewrap import BubblewrapSandboxBackend
from maistro.sandbox.backends.fake import FakeSandboxBackend
from maistro.sandbox.network import (
    DENY_ALL,
    EgressGrant,
    EgressMode,
    EgressNotEnforceableError,
    resolve_grant,
)
from maistro.sandbox.policy import (
    MODE_FLOORS,
    ExecutionMode,
    WorkloadPolicy,
    floor_for_mode,
)

HAS_BWRAP = shutil.which("bwrap") is not None
requires_bwrap = pytest.mark.skipif(HAS_BWRAP is False, reason="bubblewrap is not installed")


# --- the default -------------------------------------------------------------


def test_a_sandbox_config_denies_egress_unless_told_otherwise() -> None:
    assert SandboxConfig().egress is DENY_ALL
    assert SandboxConfig().egress.grants_network is False


def test_untrusted_code_carries_no_egress_grant() -> None:
    assert UNTRUSTED_CODE.egress.grants_network is False


# --- a grant is explicit, reasoned, and well-formed --------------------------


def test_a_grant_without_a_reason_is_refused() -> None:
    """So a grant cannot be made by accident, and an audit line always has a
    subject to name."""
    with pytest.raises(ValueError, match="requires a reason"):
        EgressGrant(mode=EgressMode.HOST)


def test_a_scoped_grant_without_destinations_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one destination"):
        EgressGrant(mode=EgressMode.SCOPED, reason="why")


def test_an_allowlist_on_an_unscoped_grant_is_refused() -> None:
    """`HOST` plus an allowlist reads as "these destinations only" and means
    the opposite. Refused rather than silently ignored."""
    with pytest.raises(ValueError, match="does not take an allowlist"):
        EgressGrant(mode=EgressMode.HOST, allow=("api.example.com",), reason="why")


def test_denied_is_the_default_grant() -> None:
    assert DENY_ALL.mode is EgressMode.DENY
    assert DENY_ALL.grants_network is False


# --- a backend refuses what it cannot enforce --------------------------------


def test_a_backend_that_cannot_filter_refuses_a_scoped_grant() -> None:
    """The failure this prevents is invisible: granting the whole host network
    while the audit trail records a scoped grant."""
    grant = EgressGrant(mode=EgressMode.SCOPED, allow=("api.example.com",), reason="one upstream")

    with pytest.raises(EgressNotEnforceableError, match="cannot filter egress"):
        resolve_grant(
            grant,
            backend_name="BubblewrapSandboxBackend",
            supports_scoped_egress=False,
            sandbox_id="s1",
        )


def test_the_bubblewrap_backend_declares_it_cannot_scope_egress() -> None:
    assert BubblewrapSandboxBackend.supports_scoped_egress is False


async def test_spawning_with_an_unenforceable_grant_fails_before_any_sandbox_exists(
    tmp_path: Path,
) -> None:
    backend = BubblewrapSandboxBackend(root=tmp_path, bwrap="/usr/bin/bwrap")
    config = SandboxConfig(
        egress=EgressGrant(mode=EgressMode.SCOPED, allow=("example.com",), reason="one host")
    )

    with pytest.raises(EgressNotEnforceableError):
        await backend.spawn(config=config)

    assert list(tmp_path.iterdir()) == [], "no workdir should survive a refused spawn"


def test_a_grant_is_audited_when_it_grants_and_when_it_denies(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """ "Auditable" is not satisfied by logging only the interesting case: a
    reader needs to be able to tell "denied" from "never asked"."""
    import logging

    with caplog.at_level(logging.INFO):
        resolve_grant(
            EgressGrant(mode=EgressMode.HOST, reason="first-party API"),
            backend_name="B",
            supports_scoped_egress=False,
            sandbox_id="s1",
        )
        resolve_grant(DENY_ALL, backend_name="B", supports_scoped_egress=False, sandbox_id="s2")

    assert "sandbox_egress_granted" in caplog.text
    assert "first-party API" in caplog.text
    assert "sandbox_egress_denied" in caplog.text


# --- execution-mode floors (ADR-093 decision 6) ------------------------------


def test_an_unstated_mode_gets_the_autonomous_floor() -> None:
    """ADR-093 says so, and the asymmetry is the reason: treating an unattended
    run as supervised is the failure that matters; the converse costs a refusal
    on a weak host."""
    assert floor_for_mode(None) == MODE_FLOORS[ExecutionMode.AUTONOMOUS]
    assert floor_for_mode(None) == "gvisor"


def test_interactive_may_stand_on_tier_three_and_autonomous_may_not() -> None:
    assert MODE_FLOORS[ExecutionMode.INTERACTIVE] == "bubblewrap"
    assert MODE_FLOORS[ExecutionMode.AUTONOMOUS] == "gvisor"


def test_the_mode_floor_raises_a_weak_policy() -> None:
    policy = WorkloadPolicy(min_tier="bubblewrap", mode=ExecutionMode.AUTONOMOUS, reason="r")

    assert policy.effective_min_tier == "gvisor"


def test_a_strong_policy_is_not_lowered_by_a_permissive_mode() -> None:
    """The stricter of the two, not the mode's. A policy needing a VM does not
    get a weaker boundary because a human happens to be watching."""
    policy = WorkloadPolicy(min_tier="vm", mode=ExecutionMode.INTERACTIVE, reason="r")

    assert policy.effective_min_tier == "vm"


def test_first_party_workloads_are_not_floored_by_mode() -> None:
    """ADR-093 decision 3 exempts trusted first-party services from microVM
    isolation as explicitly as decision 1 requires it for untrusted code.
    Applying the autonomous floor here would refuse a Jira call on every host
    without gVisor, which is the ADR being read past its own scope.
    """
    assert TRUSTED_TOOL.untrusted is False
    assert TRUSTED_TOOL.effective_min_tier == "container"
    assert BROWSER_AUTOMATION.effective_min_tier == "container"


def test_an_unattended_workload_is_refused_on_a_tier_three_host() -> None:
    selector = SandboxSelector()
    selector.register("fake", FakeSandboxBackend())
    policy = WorkloadPolicy(
        min_tier="bubblewrap",
        mode=ExecutionMode.AUTONOMOUS,
        reason="overnight builders run",
    )

    with pytest.raises(NoSuitableBackendError, match="mode floor"):
        selector.select(policy)


def test_the_refusal_says_the_mode_raised_the_requirement() -> None:
    """An operator reading "requires gvisor" on a policy that asked for
    bubblewrap needs to know which rule did that to them."""
    selector = SandboxSelector()
    policy = WorkloadPolicy(min_tier="bubblewrap", mode=ExecutionMode.AUTONOMOUS, reason="r")

    with pytest.raises(NoSuitableBackendError, match="raised from 'bubblewrap'"):
        selector.select(policy)


# --- the grant cannot be widened after the fact ------------------------------


def test_the_grant_is_frozen_onto_the_config() -> None:
    """ "Cannot be widened by candidate code" is only true if there is nothing
    to widen: the grant is decided before the sandbox exists, and there is no
    API that edits it afterwards."""
    config = SandboxConfig(egress=EgressGrant(mode=EgressMode.HOST, reason="r"))

    with pytest.raises((AttributeError, TypeError)):
        config.egress = DENY_ALL  # type: ignore[misc]
    with pytest.raises((AttributeError, TypeError)):
        config.egress.mode = EgressMode.DENY  # type: ignore[misc]


def test_build_config_takes_the_grant_from_the_policy_not_the_overrides() -> None:
    """`build_config(**overrides)` may only tighten. An override that could
    supply an egress grant would be a widening path straight through the clamp
    that exists to prevent widening."""
    selector = SandboxSelector()

    config = selector.build_config(UNTRUSTED_CODE, network=True, egress="anything")

    assert config.egress is UNTRUSTED_CODE.egress
    assert config.egress.grants_network is False


# --- and then, against the kernel --------------------------------------------


@requires_bwrap
async def test_a_denied_sandbox_has_no_interface_but_loopback(tmp_path: Path) -> None:
    backend = BubblewrapSandboxBackend(root=tmp_path)
    instance = await backend.spawn(config=SandboxConfig())

    result = await backend.exec(instance, ["/bin/cat", "/proc/net/dev"], timeout_s=30)

    names = [line.split(":")[0].strip() for line in result.stdout.splitlines() if ":" in line]
    assert [n for n in names if n and n != "lo"] == []
    await backend.destroy(instance)


@requires_bwrap
@pytest.mark.parametrize(
    ("label", "address"),
    [
        ("cloud metadata", "169.254.169.254"),
        ("private network", "10.0.0.1"),
        ("host loopback", "127.0.0.1"),
    ],
)
async def test_a_denied_sandbox_cannot_reach_any_of_the_dangerous_ranges(
    tmp_path: Path, label: str, address: str
) -> None:
    """The three that matter, and the reason a Python-level guard is not enough
    for candidate code: this opens a raw socket, not an HTTP client."""
    backend = BubblewrapSandboxBackend(root=tmp_path)
    instance = await backend.spawn(config=SandboxConfig())
    probe = (
        "import socket,sys\n"
        "s=socket.socket(); s.settimeout(2)\n"
        "try:\n"
        f"    s.connect(('{address}', 80)); print('REACHED')\n"
        "except OSError as e:\n"
        "    print('REFUSED', e.__class__.__name__)\n"
    )

    result = await backend.exec(instance, ["/usr/bin/python3", "-c", probe], timeout_s=30)

    assert "REACHED" not in result.stdout, f"{label} was reachable from a denied sandbox"
    await backend.destroy(instance)


@requires_bwrap
async def test_a_denied_sandbox_cannot_resolve_dns(tmp_path: Path) -> None:
    backend = BubblewrapSandboxBackend(root=tmp_path)
    instance = await backend.spawn(config=SandboxConfig())
    probe = (
        "import socket\n"
        "try:\n"
        "    print('RESOLVED', socket.gethostbyname('example.com'))\n"
        "except OSError as e:\n"
        "    print('REFUSED', e.__class__.__name__)\n"
    )

    result = await backend.exec(instance, ["/usr/bin/python3", "-c", probe], timeout_s=30)

    assert "RESOLVED" not in result.stdout
    await backend.destroy(instance)
