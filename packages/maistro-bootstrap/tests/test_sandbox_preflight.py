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


# --- what the operator is actually shown ---------------------------------


def _env(*, present: bool, summary: str = "…") -> dict:
    return {
        "admin_hint": "running as root",
        "virtualization": ["kvm"],
        "sandbox": {"sandbox_binary_present": present, "summary": summary},
    }


def test_the_banner_says_what_can_isolate_next_to_what_cannot() -> None:
    """The sandbox line sits beside the hypervisor inventory deliberately. The
    two used to be conflated, and "kvm" on the Virtualization line reads as
    "this host can isolate untrusted code" when the engine ships no VM backend
    at all."""
    from maistro_bootstrap.wizard import preflight_lines

    lines = preflight_lines("docker", "docker is on PATH.", _env(present=True, summary="ready"))

    assert any("Virtualization" in line and "kvm" in line for line in lines)
    assert any("Sandbox" in line and "ready" in line for line in lines)


def test_a_host_that_cannot_isolate_is_shown_in_warning_colour() -> None:
    """Not decoration. On this host the engine will refuse to run a workload,
    so the line is a refusal waiting to happen rather than a note — and it is
    the only line in the banner that is."""
    from maistro_bootstrap.wizard import preflight_lines

    lines = preflight_lines("docker", "hint", _env(present=False, summary="install bubblewrap"))

    assert [line for line in lines if line.startswith("[yellow]")] == [
        "[yellow]Sandbox:[/yellow] install bubblewrap\n"
    ]


def test_a_host_that_can_isolate_is_not_shouted_about() -> None:
    from maistro_bootstrap.wizard import preflight_lines

    lines = preflight_lines("docker", "hint", _env(present=True))

    assert not [line for line in lines if line.startswith("[yellow]")]


def test_every_banner_line_is_printed(monkeypatch) -> None:
    """`preflight_lines` is only worth testing if something shows the operator
    what it returns. This is the seam between the two."""
    from maistro_bootstrap import wizard

    printed: list[str] = []
    monkeypatch.setattr(wizard.console, "print", printed.append)

    wizard.print_preflight("docker", "hint", _env(present=False, summary="install bubblewrap"))

    assert printed == wizard.preflight_lines(
        "docker", "hint", _env(present=False, summary="install bubblewrap")
    )
    assert len(printed) == 4


def test_the_banner_is_shown_before_the_wizard_asks_anything(monkeypatch) -> None:
    """Order matters: the sandbox line tells an operator whether this host can
    run workloads at all, and it is worth nothing after they have answered
    twenty questions. Stopping at the first prompt is what proves the banner
    came first rather than merely appearing somewhere in the transcript."""
    from maistro_bootstrap import wizard

    printed: list[str] = []
    monkeypatch.setattr(wizard.console, "print", lambda *a, **k: printed.append(a[0] if a else ""))
    monkeypatch.setattr(wizard, "detect_container_runtime", lambda: ("docker", "hint"))
    monkeypatch.setattr(wizard, "environment_report", lambda: _env(present=False, summary="none"))

    class FirstPrompt(Exception):
        pass

    def _stop() -> None:
        raise FirstPrompt

    monkeypatch.setattr(wizard, "_stack_bringup", _stop)

    with pytest.raises(FirstPrompt):
        wizard.collect_answers_interactive()

    assert any("Sandbox" in str(line) for line in printed)
