"""The sandbox ladder is a measurement, not a claim (ADR-093, #76).

Before this the subsystem had a selector, five policies and one fake backend,
and nothing assembled them. Every property the ladder promises — strongest tier
wins, weaker tiers refuse, nothing runs when nothing is available — was
therefore unfalsifiable in a shipped configuration: no caller built a selector,
so no caller could be refused by one.

Two things are separated deliberately here. Whether `bwrap` *isolates* is the
kernel's job and is asserted only where `bwrap` exists. Which flags it is given
is this repository's job, and is asserted everywhere, because that is the whole
security content of a Tier-3 backend and it would otherwise go unverified on
every machine without bubblewrap installed — which is most of them.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from maistro.sandbox import (
    UNTRUSTED_CODE,
    HostCapabilities,
    NoSuitableBackendError,
    SandboxConfig,
    SandboxSelector,
    TierMismatchError,
    build_selector,
    detect_host_capabilities,
)
from maistro.sandbox.backends.bubblewrap import (
    BubblewrapSandboxBackend,
    BubblewrapUnavailableError,
)
from maistro.sandbox.backends.fake import FakeSandboxBackend
from maistro.sandbox.policy import WorkloadPolicy

#: Capability, not binary presence. A host can have `bwrap` on PATH and be
#: unable to build the namespace with it -- Ubuntu 24.04 restricting
#: unprivileged user namespaces is the case that taught us -- and a suite
#: keyed on `which` would run the kernel assertions there and fail.
HAS_BWRAP = detect_host_capabilities().supports("bubblewrap")
requires_bwrap = pytest.mark.skipif(
    HAS_BWRAP is False, reason="this host cannot build a bubblewrap sandbox"
)


def _caps(*tiers: str) -> HostCapabilities:
    return HostCapabilities(tiers=tuple(tiers), notes={})


# --- the fail-open the selector used to permit --------------------------------


def test_a_backend_cannot_be_registered_as_a_stronger_boundary() -> None:
    """The hole this closes: `register("vm", FakeSandboxBackend())` was legal.

    That single call made in-process `subprocess.run` satisfy `UNTRUSTED_CODE`,
    whose entire stated reason is that model-generated code must run behind a
    VM boundary — and everything downstream trusts the tier, so nothing else
    would have caught it.
    """
    selector = SandboxSelector()

    with pytest.raises(TierMismatchError, match="cannot be relabelled"):
        selector.register("vm", FakeSandboxBackend())

    assert selector.available_tiers == []


def test_a_backend_registered_at_its_declared_tier_is_accepted() -> None:
    selector = SandboxSelector()

    selector.register("fake", FakeSandboxBackend())

    assert selector.available_tiers == ["fake"]


# --- detection reports what is there, not what is hoped for -------------------


def test_detection_names_a_reason_for_every_absent_tier() -> None:
    """An absent tier without a reason is indistinguishable from an unasked
    question, and the operator reading this is trying to find out which."""
    caps = detect_host_capabilities()

    for tier in ("vm", "gvisor", "bubblewrap"):
        assert caps.supports(tier) or caps.notes.get(tier)


def test_kvm_present_but_unopenable_is_not_hardware_virtualization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The case `Path.exists()` gets wrong. `/dev/kvm` is routinely visible
    inside a container with no access to it, and a host reporting Tier 1 on the
    strength of a visible device node fails at spawn — after the policy check
    that existed to prevent exactly that."""
    from maistro.sandbox import detect

    monkeypatch.setattr(detect.Path, "exists", lambda _self: True)
    monkeypatch.setattr(detect.os, "access", lambda *_a, **_k: False)

    caps = detect.detect_host_capabilities()

    assert not caps.supports("vm")
    assert "not readable/writable" in caps.notes["vm"]


def test_kvm_without_a_vmm_is_not_hardware_virtualization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """KVM is necessary and not sufficient: something has to drive it."""
    from maistro.sandbox import detect

    monkeypatch.setattr(detect, "_kvm_usable", lambda: (True, ""))
    monkeypatch.setattr(detect, "_which", lambda _binary: None)

    caps = detect.detect_host_capabilities()

    assert not caps.supports("vm")
    assert "no VMM found" in caps.notes["vm"]


# --- assembly, and the fail-closed rule ---------------------------------------


def test_a_host_with_nothing_refuses_every_workload() -> None:
    """ADR-093: "if none of the above is present, refuse to execute. There is
    no bare-subprocess tier." """
    selector = build_selector(capabilities=_caps())

    assert selector.available_tiers == []
    with pytest.raises(NoSuitableBackendError):
        selector.select(UNTRUSTED_CODE)


def test_the_fake_is_never_registered_automatically() -> None:
    """A dev convenience that appears without being asked for is how a
    production host ends up "isolating" nothing."""
    assert build_selector(capabilities=_caps()).available_tiers == []
    assert build_selector(capabilities=_caps(), allow_fake=True).available_tiers == ["fake"]


def test_a_bubblewrap_host_still_refuses_untrusted_code() -> None:
    """Tier 3 is a guardrail against accidents, not a boundary against hostile
    code, and ADR-093 says so. The ladder must refuse rather than quietly
    landing model-generated code on the weakest rung it happens to have."""
    caps = _caps("bubblewrap")
    if not HAS_BWRAP:
        pytest.skip("bubblewrap is not installed; construction would refuse first")

    selector = build_selector(capabilities=caps)

    assert selector.strongest_tier == "bubblewrap"
    with pytest.raises(NoSuitableBackendError):
        selector.select(UNTRUSTED_CODE)


def test_detection_and_construction_can_disagree_without_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A binary can leave PATH between the probe and the build. Believe the
    build: an unregistered tier refuses, a half-built one would raise on first
    use instead."""
    import maistro.sandbox.backends.bubblewrap as bwrap_module

    def _refuse(*_args: object, **_kwargs: object) -> None:
        raise BubblewrapUnavailableError("gone")

    monkeypatch.setattr(bwrap_module, "BubblewrapSandboxBackend", _refuse)

    selector = build_selector(capabilities=_caps("bubblewrap"))

    assert selector.available_tiers == []


# --- the backend's security content: its flags --------------------------------


def _backend(tmp_path: Path) -> BubblewrapSandboxBackend:
    return BubblewrapSandboxBackend(root=tmp_path, bwrap="/usr/bin/bwrap")


def test_the_sandbox_is_unshared_capability_dropped_and_detached(tmp_path: Path) -> None:
    """Asserted as flags rather than behaviour so they are verified on hosts
    without bubblewrap too — which is where they would otherwise rot."""
    argv = _backend(tmp_path).build_argv(SandboxConfig(), tmp_path, ["true"])

    assert "--unshare-all" in argv
    assert "--die-with-parent" in argv
    assert argv[argv.index("--cap-drop") + 1] == "ALL"
    # Without a fresh session the sandboxed process keeps the caller's
    # controlling terminal and can push characters back into it with TIOCSTI,
    # which is an escape from a sandbox that otherwise looks airtight.
    assert "--new-session" in argv


def test_the_network_is_absent_unless_the_config_grants_it(tmp_path: Path) -> None:
    backend = _backend(tmp_path)

    without = backend.build_argv(SandboxConfig(network=False), tmp_path, ["true"])
    with_net = backend.build_argv(SandboxConfig(network=True), tmp_path, ["true"])

    assert "--share-net" not in without
    assert "--share-net" in with_net


def test_the_environment_is_cleared_rather_than_inherited(tmp_path: Path) -> None:
    """An inherited environment carries the host's credentials into the
    sandbox, which is #78's whole subject and free to get right here."""
    argv = _backend(tmp_path).build_argv(SandboxConfig(env={"SAFE": "1"}), tmp_path, ["true"])

    assert "--clearenv" in argv
    assert argv[argv.index("--setenv") + 1 : argv.index("--setenv") + 3] == ["SAFE", "1"]


def test_the_only_writable_surface_is_the_sandbox_workdir(tmp_path: Path) -> None:
    argv = _backend(tmp_path).build_argv(SandboxConfig(), tmp_path, ["true"])

    binds = [argv[i + 1] for i, token in enumerate(argv) if token == "--bind"]
    assert binds == [str(tmp_path)]
    assert "--ro-bind" in argv


def test_a_backend_refuses_to_exist_where_it_cannot_isolate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Constructing anyway would produce an object that looks like a sandbox
    and is not one."""
    monkeypatch.setattr(shutil, "which", lambda _binary: None)

    with pytest.raises(BubblewrapUnavailableError, match="refusing"):
        BubblewrapSandboxBackend()


# --- file transfer cannot be used to reach the host ---------------------------


async def test_writing_outside_the_sandbox_root_is_refused(tmp_path: Path) -> None:
    """These run on the host side — they are how work gets in and results come
    out — so an unchecked path is a host write with no sandbox involved."""
    backend = _backend(tmp_path)
    instance = await backend.spawn(config=SandboxConfig())

    for escape in ("../escaped", "/work/../../escaped", "/etc/passwd"):
        with pytest.raises(ValueError, match="sandbox"):
            await backend.write_file(instance, escape, b"x")

    await backend.destroy(instance)


async def test_files_round_trip_through_the_sandbox_workdir(tmp_path: Path) -> None:
    backend = _backend(tmp_path)
    instance = await backend.spawn(config=SandboxConfig())

    await backend.write_file(instance, "/work/in.txt", b"payload")

    assert await backend.read_file(instance, "in.txt") == b"payload"
    await backend.destroy(instance)


async def test_destroy_is_idempotent_and_removes_the_workdir(tmp_path: Path) -> None:
    backend = _backend(tmp_path)
    instance = await backend.spawn(config=SandboxConfig())
    workdir = Path(instance.metadata["workdir"])
    assert workdir.exists()

    await backend.destroy(instance)
    await backend.destroy(instance)

    assert not workdir.exists()


async def test_a_destroyed_sandbox_cannot_be_used(tmp_path: Path) -> None:
    backend = _backend(tmp_path)
    instance = await backend.spawn(config=SandboxConfig())
    await backend.destroy(instance)

    with pytest.raises(KeyError):
        await backend.read_file(instance, "in.txt")


# --- and then, where the kernel is available, that it really isolates ---------


@requires_bwrap
async def test_a_real_sandbox_executes_and_reports_its_result(tmp_path: Path) -> None:
    backend = BubblewrapSandboxBackend(root=tmp_path)
    instance = await backend.spawn(config=SandboxConfig())

    result = await backend.exec(instance, ["/bin/sh", "-c", "echo hello"], timeout_s=30)

    assert result.exit_code == 0
    assert result.stdout.strip() == "hello"
    await backend.destroy(instance)


@requires_bwrap
async def test_a_real_sandbox_cannot_see_the_host_filesystem(tmp_path: Path) -> None:
    """The claim the flags are for, checked against the kernel rather than
    against the argv."""
    secret = tmp_path / "host-secret"
    secret.write_text("do not read me")
    backend = BubblewrapSandboxBackend(root=tmp_path)
    instance = await backend.spawn(config=SandboxConfig())

    result = await backend.exec(instance, ["/bin/cat", str(secret)], timeout_s=30)

    assert result.exit_code != 0
    assert "do not read me" not in result.stdout
    await backend.destroy(instance)


@requires_bwrap
async def test_a_real_sandbox_times_out_rather_than_running_forever(tmp_path: Path) -> None:
    backend = BubblewrapSandboxBackend(root=tmp_path)
    instance = await backend.spawn(config=SandboxConfig())

    result = await backend.exec(instance, ["/bin/sleep", "30"], timeout_s=1)

    assert result.timed_out
    assert result.exit_code == 124
    await backend.destroy(instance)


@requires_bwrap
async def test_a_real_sandbox_has_no_network_by_default(tmp_path: Path) -> None:
    backend = BubblewrapSandboxBackend(root=tmp_path)
    instance = await backend.spawn(config=SandboxConfig(network=False))

    result = await backend.exec(
        instance,
        ["/bin/sh", "-c", "cat /proc/net/dev"],
        timeout_s=30,
    )

    # An unshared network namespace has loopback and nothing else.
    interfaces = [line.split(":")[0].strip() for line in result.stdout.splitlines() if ":" in line]
    assert [name for name in interfaces if name and name != "lo"] == []
    await backend.destroy(instance)


@requires_bwrap
def test_a_host_that_can_isolate_reports_the_bubblewrap_tier() -> None:
    assert detect_host_capabilities().supports("bubblewrap")


def test_a_policy_asking_for_a_tier_nobody_registered_is_refused() -> None:
    selector = SandboxSelector()
    selector.register("fake", FakeSandboxBackend())
    policy = WorkloadPolicy(min_tier="gvisor", reason="unattended floor")

    with pytest.raises(NoSuitableBackendError, match="gvisor"):
        selector.select(policy)


def test_a_present_binary_that_cannot_isolate_is_not_a_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gap a `which` check leaves, and it is not theoretical.

    On a host restricting unprivileged user namespaces — Ubuntu 24.04 with
    `kernel.apparmor_restrict_unprivileged_userns=1`, which is what GitHub's
    runners ship — `bwrap` is installed and `--unshare-all` fails at
    `loopback: Failed RTM_NEWADDR: Operation not permitted`. Reporting Tier 3
    from the binary's existence puts a workload on a boundary that cannot be
    built, and the failure lands at spawn: after the policy check that existed
    to prevent exactly that.
    """
    import subprocess

    from maistro.sandbox import detect

    monkeypatch.setattr(detect, "_which", lambda binary: "/usr/bin/bwrap")
    monkeypatch.setattr(
        detect.subprocess,
        "run",
        lambda *_a, **_k: subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout=b"",
            stderr=b"bwrap: loopback: Failed RTM_NEWADDR: Operation not permitted\n",
        ),
    )

    caps = detect.detect_host_capabilities()

    assert not caps.supports("bubblewrap")
    assert "RTM_NEWADDR" in caps.notes["bubblewrap"]


def test_a_probe_that_cannot_run_at_all_is_not_a_tier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A probe that raises must read as "no", not propagate out of startup."""
    from maistro.sandbox import detect

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise OSError("no exec")

    monkeypatch.setattr(detect, "_which", lambda binary: "/usr/bin/bwrap")
    monkeypatch.setattr(detect.subprocess, "run", _boom)

    caps = detect.detect_host_capabilities()

    assert not caps.supports("bubblewrap")
    assert "could not run" in caps.notes["bubblewrap"]


# --- the operator entry point -------------------------------------------------


def _cli(*args: str) -> str:
    from typer.testing import CliRunner

    from maistro.cli import app

    result = CliRunner().invoke(app, list(args))
    assert result.exit_code == 0, result.output
    return result.output


def test_an_operator_can_read_what_this_host_provides() -> None:
    """The operational half of the support matrix. That page says what each
    tier requires; this answers which one *this* machine gives you."""
    output = _cli("sandbox", "status")

    assert "strongest available tier" in output
    for tier in ("vm", "gvisor", "bubblewrap"):
        assert tier in output


def test_the_report_says_why_a_tier_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """A host where `bwrap` is installed but user namespaces are restricted
    looks identical from outside to one where it is absent. The difference is
    the note, and before this command there was no way to read it short of
    importing the library."""
    from maistro.sandbox import detect

    monkeypatch.setattr(
        detect,
        "detect_host_capabilities",
        lambda: HostCapabilities(tiers=(), notes={"bubblewrap": "RTM_NEWADDR refused"}),
    )
    import maistro.cli._sandbox as sandbox_cli

    monkeypatch.setattr(
        sandbox_cli,
        "detect_host_capabilities",
        lambda: HostCapabilities(tiers=(), notes={"bubblewrap": "RTM_NEWADDR refused"}),
    )

    output = _cli("sandbox", "status")

    assert "RTM_NEWADDR refused" in output
    assert "No sandbox backend is available" in output
