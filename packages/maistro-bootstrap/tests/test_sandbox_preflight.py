"""The installer may not imply isolation it has not measured (#81).

`environment_report()` reported `kvm_device: bool` under a heading called
"Virtualization". To an operator with no reason to know the difference, that
reads as "this host can isolate untrusted code" — and #76 established that a
visible `/dev/kvm` is *not* Tier 1: the device has to open and a VMM has to
exist. Worse, the engine ships no VM backend at all, so even a genuine Tier-1
host would not get VM isolation from it today.

The installer runs before the engine is installed and cannot import the
engine's detector, so the fix is not a better probe here. It is to report
hints as hints, report the one binary that maps to a working tier, and name
`maistro sandbox status` as the thing that settles it.
"""

from __future__ import annotations

import pytest

from maistro_bootstrap import platform_detect
from maistro_bootstrap.platform_detect import (
    SANDBOX_AUTHORITY,
    SANDBOX_BINARY,
    environment_report,
    sandbox_readiness,
)


@pytest.fixture
def host(monkeypatch):
    """A host where nothing is installed until the test says so."""

    def present(*names: str) -> None:
        monkeypatch.setattr(platform_detect, "has_command", lambda name: name in names)

    monkeypatch.setattr(platform_detect.Path, "exists", lambda self: False)
    present()
    return present


def test_a_host_without_the_sandbox_binary_is_told_so_and_told_what_to_install(host) -> None:
    """The actionable-failure requirement. "bubblewrap: false" is a fact an
    operator cannot act on without knowing what it costs them or what to type."""
    report = sandbox_readiness()

    assert report["sandbox_binary_present"] is False
    assert "refuse" in report["summary"]
    assert f"apt install {SANDBOX_BINARY}" in report["summary"]


def test_a_host_with_the_sandbox_binary_is_still_told_to_confirm(host) -> None:
    """`which bwrap` is not the answer either: a host can have it on PATH and
    be unable to build the namespace, which is what taught #76 to probe."""
    host("bwrap")

    report = sandbox_readiness()

    assert report["sandbox_binary_present"] is True
    assert SANDBOX_AUTHORITY in report["summary"]


def test_a_kvm_node_is_reported_as_inventory_not_capability(host, monkeypatch) -> None:
    """The misreading this issue is about. The key name says what it is — a
    device node was *seen* — and the report says outright that the stronger
    tiers have no backend, so this changes nothing about what will run."""
    monkeypatch.setattr(platform_detect.Path, "exists", lambda self: True)

    report = sandbox_readiness()

    assert report["kvm_device_node_seen"] is True
    assert "not capability" in report["stronger_tiers"]


def test_a_vmm_binary_is_named_when_one_is_there(host) -> None:
    host("firecracker")

    assert sandbox_readiness()["vmm_binary_seen"] == "firecracker"


def test_no_vmm_binary_reports_nothing_rather_than_a_default(host) -> None:
    assert sandbox_readiness()["vmm_binary_seen"] is None


def test_the_environment_report_carries_the_sandbox_section(host) -> None:
    """Separate from `virtualization`, which is the host's hypervisor
    inventory and says nothing about the sandbox ladder. Conflating them is
    what made the old report misleading."""
    report = environment_report()

    assert "sandbox" in report
    assert report["sandbox"]["authority"] == SANDBOX_AUTHORITY
    assert report["sandbox"]["sandbox_binary_present"] is False
