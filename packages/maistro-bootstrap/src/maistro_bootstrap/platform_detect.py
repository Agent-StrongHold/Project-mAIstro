"""Lightweight OS / runtime detection for the install wizard."""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


def uname_summary() -> str:
    u = platform.uname()
    return f"{u.system} {u.release} ({u.machine})"


def is_wsl() -> bool:
    rel = platform.release().lower()
    if "microsoft" in rel or "wsl" in rel:
        return True
    try:
        return (
            "microsoft"
            in Path("/proc/version").read_text(encoding="utf-8", errors="replace").lower()
        )
    except OSError:
        return False


def linux_distro_guess() -> str | None:
    try:
        os_release = Path("/etc/os-release").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.search(r'^PRETTY_NAME="([^"]+)"', os_release, re.MULTILINE)
    if m:
        return m.group(1)
    m2 = re.search(r"^PRETTY_NAME=(.+)$", os_release, re.MULTILINE)
    return m2.group(1).strip('"') if m2 else None


def deployment_hint() -> str:
    sys = platform.system().lower()
    if sys == "darwin":
        return "macOS: Homebrew is common for Docker Desktop or Colima; see https://brew.sh/"
    if sys == "linux":
        if is_wsl():
            return "WSL2: use Docker Desktop WSL integration or Docker Engine inside the distro."
        d = linux_distro_guess()
        if d:
            return f"Linux ({d}): install Docker Engine or Podman per distro docs."
        return "Linux: install Docker Engine or Podman per distro docs."
    if sys == "windows":
        return "Windows: use WSL2 + Linux installer path, or Docker Desktop."
    return "Unknown platform: use a Linux VM or supported container host."


def has_command(name: str) -> bool:
    return shutil.which(name) is not None


def _run_probe(argv: list[str], timeout: float = 2.0) -> tuple[bool, str]:
    try:
        proc = subprocess.run(argv, text=True, capture_output=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    out = (proc.stdout or proc.stderr).strip().splitlines()
    return proc.returncode == 0, out[0] if out else f"exit {proc.returncode}"


def deployment_tier_gate_message(tier: str) -> str | None:
    """Non-blocking guidance when compose automation is not assumed for this tier."""
    if tier == "proxmox":
        return (
            "Proxmox: the installer does not configure hypervisors. Run Docker/Podman on a "
            "Linux VM or bare-metal guest, then use stack_bringup from that environment."
        )
    if tier == "lxc":
        return (
            "LXC: privilege and cgroup policies vary; prefer a VM with a supported Docker Engine "
            "install, then point MAISTRO_REPO_ROOT at your clone."
        )
    if tier == "vm":
        return (
            "VM: ensure Docker Engine or Podman is installed inside the VM; maistro-install "
            "detects repo root from the VM filesystem."
        )
    return None


def detect_container_runtime() -> tuple[str, str]:
    """Return (detected, hint) where detected is docker | podman | none."""
    d, p = has_command("docker"), has_command("podman")
    if d and p:
        return "both", "Both docker and podman are on PATH; pick one in answers."
    if d:
        return "docker", "docker is on PATH."
    if p:
        return "podman", "podman is on PATH (no docker)."
    return "none", "No docker/podman on PATH — install a container runtime first."


#: The one sandbox backend that ships (ADR-093, #76). Tiers 1 and 2 are probed
#: by the engine and have no backend, so this is the only binary whose presence
#: the installer can turn into a working isolation tier.
SANDBOX_BINARY = "bubblewrap"

#: The engine's own detector is the authority on what a host can isolate, and
#: it is a *functional* probe: #76 found hosts with `/dev/kvm` visible and
#: unopenable, and hosts with `bwrap` on PATH that cannot build a namespace
#: because the distribution restricts unprivileged user namespaces. The
#: installer runs before the engine is installed and cannot import it, so it
#: reports hints and says where the answer lives.
SANDBOX_AUTHORITY = "maistro sandbox status"


def sandbox_readiness() -> dict[str, Any]:
    """What the installer can honestly say about isolation before the engine exists (#81).

    Deliberately *hints*, not capabilities. `/dev/kvm` being present is not
    Tier 1 — a VMM has to exist and the device has to open, which is the check
    the engine makes and this one cannot. Reporting a boolean called
    `kvm_device` beside a heading called "Virtualization" reads as "you have VM
    isolation" to an operator who has no reason to know the difference, and
    that is the misreading this issue is about.

    So each line says what was seen, and the report names
    `maistro sandbox status` as the thing that settles it once the engine is
    installed.
    """
    kvm_node = Path("/dev/kvm").exists()
    vmm = next(
        (
            name
            for name in ("firecracker", "cloud-hypervisor", "qemu-system-x86_64")
            if has_command(name)
        ),
        None,
    )
    bwrap = has_command("bwrap")

    if bwrap:
        summary = (
            f"{SANDBOX_BINARY} is installed, so this host can probably reach the one tier that "
            f"ships a backend. Confirm with `{SANDBOX_AUTHORITY}` after install — the engine "
            "probes rather than assumes."
        )
    else:
        summary = (
            f"{SANDBOX_BINARY} is not installed. Nothing this engine ships can isolate a "
            "workload on this host, and it will refuse to run one rather than fall back to a "
            f"bare subprocess. Install it (Debian/Ubuntu: `apt install {SANDBOX_BINARY}`; "
            f"Fedora: `dnf install {SANDBOX_BINARY}`), then confirm with `{SANDBOX_AUTHORITY}`."
        )

    return {
        "sandbox_binary_present": bwrap,
        "summary": summary,
        "authority": SANDBOX_AUTHORITY,
        # Hints for the stronger tiers, named as hints. Neither has a backend
        # in this engine yet, so neither changes what will run today.
        "kvm_device_node_seen": kvm_node,
        "vmm_binary_seen": vmm,
        "stronger_tiers": (
            "Tiers 1 (microVM) and 2 (gVisor) are probed by the engine and have no backend "
            "here yet, so these two lines are inventory, not capability."
        ),
    }


def environment_report() -> dict[str, Any]:
    """Best-effort installer preflight; no mutations and no secrets."""
    sys = platform.system().lower()
    docker_ok, docker_msg = _run_probe(["docker", "info", "--format", "{{.ServerVersion}}"])
    podman_ok, podman_msg = _run_probe(
        ["podman", "info", "--format", "{{.Host.Os}}/{{.Host.Arch}}"]
    )
    kvm = Path("/dev/kvm").exists()
    hyperv = has_command("powershell.exe") and "microsoft" in platform.release().lower()
    admin = False
    admin_hint = "not root/admin; installer will prefer user-scoped setup and print sudo steps"
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        admin = True
        admin_hint = "running as root; safe defaults still avoid host-wide changes unless confirmed"
    elif sys == "windows":
        ok, _msg = _run_probe(["net", "session"])
        admin = ok
        admin_hint = "Windows admin available" if ok else "Windows admin not detected"

    runtime, runtime_hint = detect_container_runtime()
    virtualization: list[str] = []
    if kvm:
        virtualization.append("kvm")
    if hyperv:
        virtualization.append("hyperv/wsl")
    if is_wsl():
        virtualization.append("wsl2")

    return {
        "os": uname_summary(),
        "distro": linux_distro_guess(),
        "is_wsl": is_wsl(),
        "admin_available": admin,
        "admin_hint": admin_hint,
        "container_runtime": runtime,
        "container_runtime_hint": runtime_hint,
        "docker_daemon": {"ok": docker_ok, "message": docker_msg},
        "podman_machine": {"ok": podman_ok, "message": podman_msg},
        "virtualization": virtualization or ["none-detected"],
        "kvm_device": kvm,
        "hyperv_hint": hyperv,
        # What the engine can actually isolate with, kept separate from the
        # `virtualization` line above, which is about the host's hypervisor
        # inventory and says nothing about the sandbox ladder (#81).
        "sandbox": sandbox_readiness(),
    }
