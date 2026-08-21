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
    }
