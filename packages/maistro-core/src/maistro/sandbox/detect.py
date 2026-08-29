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


def detect_host_capabilities() -> HostCapabilities:
    """Probe the host once and report the tiers it can really provide."""
    tiers: list[IsolationTier] = []
    notes: dict[IsolationTier, str] = {}

    kvm_ok, kvm_note = _kvm_usable()
    vmm = next((name for name in VMM_BINARIES if _which(name)), None)
    if kvm_ok and vmm is not None:
        tiers.append("vm")
    elif not kvm_ok:
        notes["vm"] = kvm_note
    else:
        notes["vm"] = f"{KVM_DEVICE} is usable but no VMM found on PATH ({', '.join(VMM_BINARIES)})"

    if _which(GVISOR_BINARY):
        tiers.append("gvisor")
    else:
        notes["gvisor"] = f"{GVISOR_BINARY!r} is not on PATH"

    if _which(BUBBLEWRAP_BINARY):
        tiers.append("bubblewrap")
    else:
        notes["bubblewrap"] = f"{BUBBLEWRAP_BINARY!r} is not on PATH"

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
