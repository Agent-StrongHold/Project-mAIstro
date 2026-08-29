"""What isolation this host can actually provide (ADR-093, #76).

The selector's fallback ladder is only as honest as the answer to "which tiers
are really here". Until now nothing asked: the only registered backend was the
fake, so `strongest_tier` reported whatever a caller had registered rather than
what the machine could do.

Probes are deliberately cheap and read-only — a binary on `PATH`, a device
node, a sysctl. Detection must be safe to run at startup on every host,
including one where the answer is "nothing", and it must never be the thing
that decides whether a workload is *allowed*: it reports capability, and
`WorkloadPolicy` decides what capability is sufficient.

Nothing here reports a tier it has not evidenced. A probe that cannot tell
returns absent, because the failure mode this exists to prevent is a host
claiming a containment boundary it does not have.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from maistro.sandbox.policy import _TIER_ORDER, IsolationTier

logger = logging.getLogger("maistro.sandbox.detect")

#: Device node that makes hardware virtualization (Tier 1) possible at all.
KVM_DEVICE = "/dev/kvm"

#: Tier-1 VMMs, in no particular preference order — any one of them, with KVM,
#: is a hardware-virtualization boundary.
VMM_BINARIES = ("firecracker", "cloud-hypervisor", "qemu-system-x86_64")

#: Tier-2: gVisor's runtime binary. Its user-space kernel is what removes the
#: host kernel from the direct syscall path.
GVISOR_BINARY = "runsc"

#: Tier-3: the OS-sandbox binary this repository supports.
BUBBLEWRAP_BINARY = "bwrap"


@dataclass(frozen=True)
class HostCapabilities:
    """What the host evidenced, and why anything missing is missing."""

    tiers: tuple[IsolationTier, ...]
    notes: dict[IsolationTier, str]

    @property
    def strongest(self) -> IsolationTier | None:
        for tier in _TIER_ORDER:
            if tier in self.tiers:
                return tier
        return None

    def supports(self, tier: IsolationTier) -> bool:
        return tier in self.tiers


def _kvm_usable() -> tuple[bool, str]:
    """KVM needs to exist *and* be openable by this process.

    Present-but-unopenable is the interesting case and the reason this does
    more than `Path.exists()`: `/dev/kvm` is routinely visible inside a
    container that has no access to it, and a host that reports Tier 1 on the
    strength of a device node it cannot open would fail at spawn time — after
    the policy check that was supposed to prevent exactly that.
    """
    device = Path(KVM_DEVICE)
    if not device.exists():
        return False, f"{KVM_DEVICE} is absent; no hardware virtualization"
    if not os.access(KVM_DEVICE, os.R_OK | os.W_OK):
        return False, f"{KVM_DEVICE} exists but is not readable/writable by this process"
    return True, ""


def _which(binary: str) -> str | None:
    return shutil.which(binary)


#: How long the bubblewrap functional probe may take. It spawns `true` in a
#: fresh namespace; a second is generous and bounds startup on a wedged host.
PROBE_TIMEOUT_S = 5


def _bubblewrap_isolates(bwrap: str) -> tuple[bool, str]:
    """Whether `bwrap` can build the namespace this backend needs, here.

    A `which` check is not enough, and the gap is not theoretical: on a host
    that restricts unprivileged user namespaces -- Ubuntu 24.04 with
    `kernel.apparmor_restrict_unprivileged_userns=1`, which is what GitHub's
    runners ship -- the binary is present and `--unshare-all` fails at
    `loopback: Failed RTM_NEWADDR: Operation not permitted`. Reporting Tier 3
    from the binary's existence would put a workload on a boundary that cannot
    be built, and the failure would arrive at spawn: after the policy check
    that exists to prevent exactly that.

    So the probe runs the same unshares the backend runs. What it proves is
    narrow and deliberate -- that the namespace can be created, not that it
    contains anything -- because that is the part hosts actually differ on.
    """
    truth = shutil.which("true")
    if truth is None:  # pragma: no cover - a host without coreutils
        return False, "no 'true' binary to probe with"

    argv = [
        bwrap,
        "--unshare-all",
        "--die-with-parent",
        "--new-session",
        "--proc",
        "/proc",
        "--dev",
        "/dev",
        "--tmpfs",
        "/tmp",  # nosec B108 — mount point inside the probe sandbox, not a host path
    ]
    for path in ("/usr", "/bin", "/lib", "/lib64"):
        if Path(path).exists():
            argv += ["--ro-bind", path, path]
    argv += ["--", truth]

    try:
        completed = subprocess.run(  # nosec B603 — fixed argv, no shell, no user input
            argv,
            capture_output=True,
            timeout=PROBE_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"bubblewrap probe could not run: {exc}"

    if completed.returncode == 0:
        return True, ""
    detail = completed.stderr.decode(errors="replace").strip().splitlines()
    return (
        False,
        f"bubblewrap cannot build an isolated namespace here: {detail[-1] if detail else completed.returncode}",
    )


def _probe_vm() -> tuple[bool, str]:
    """Tier 1 needs KVM this process can open *and* a VMM to drive it."""
    kvm_ok, kvm_note = _kvm_usable()
    if not kvm_ok:
        return False, kvm_note
    if next((name for name in VMM_BINARIES if _which(name)), None) is None:
        return False, f"{KVM_DEVICE} is usable but no VMM found on PATH ({', '.join(VMM_BINARIES)})"
    return True, ""


def _probe_gvisor() -> tuple[bool, str]:
    if _which(GVISOR_BINARY) is None:
        return False, f"{GVISOR_BINARY!r} is not on PATH"
    return True, ""


def _probe_bubblewrap() -> tuple[bool, str]:
    bwrap = _which(BUBBLEWRAP_BINARY)
    if bwrap is None:
        return False, f"{BUBBLEWRAP_BINARY!r} is not on PATH"
    return _bubblewrap_isolates(bwrap)


#: One probe per tier, strongest first. A tier is present only when its probe
#: says so, and absent tiers carry the probe's own reason.
_PROBES: tuple[tuple[IsolationTier, Callable[[], tuple[bool, str]]], ...] = (
    ("vm", _probe_vm),
    ("gvisor", _probe_gvisor),
    ("bubblewrap", _probe_bubblewrap),
)


def detect_host_capabilities() -> HostCapabilities:
    """Probe the host once and report the tiers it can really provide."""
    tiers: list[IsolationTier] = []
    notes: dict[IsolationTier, str] = {}

    for tier, probe in _PROBES:
        available, why = probe()
        if available:
            tiers.append(tier)
        else:
            notes[tier] = why

    capabilities = HostCapabilities(tiers=tuple(tiers), notes=notes)
    logger.info(
        "sandbox_host_capabilities tiers=%s strongest=%s",
        ",".join(capabilities.tiers) or "none",
        capabilities.strongest or "none",
    )
    return capabilities


__all__ = [
    "BUBBLEWRAP_BINARY",
    "GVISOR_BINARY",
    "KVM_DEVICE",
    "VMM_BINARIES",
    "HostCapabilities",
    "detect_host_capabilities",
]
