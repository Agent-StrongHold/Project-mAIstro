"""Live provisioning regression for the rootless Builder conformance lane.

Opt in on the designated Linux lane with passwordless sudo. This tests only
host provisioning; test_container_sandbox.py still exercises the unmodified
production ContainerBuilderSandbox against the resulting real daemon.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(
    os.environ.get("MAISTRO_TEST_ROOTLESS_LANE") != "1",
    reason="requires the designated Linux rootless lane with passwordless sudo",
)
def test_lane_masks_securityfs_privately_and_drops_privileges() -> None:
    """Reproduce visible-but-unreadable AppArmor discovery without host changes."""
    wrapper = Path(__file__).resolve().parents[3] / "scripts" / "ci-rootless-mountns.sh"
    assert os.getuid() != 0, "the lane must start as an unprivileged user"
    original_mounts = Path("/proc/self/mountinfo").read_text()
    # The outer namespace models the runner's unreadable AppArmor profiles.
    # Even the fixture mount must not propagate to the actual host. The inner
    # namespace is created by exactly the wrapper used to launch CI dockerd.
    result = subprocess.run(
        [
            "sudo",
            "-n",
            "unshare",
            "--mount",
            "--propagation",
            "private",
            "bash",
            "-euc",
            r"""
mount -t tmpfs -o nosuid,nodev,noexec,size=64k lane-fixture /sys/kernel/security
mkdir /sys/kernel/security/apparmor
touch /sys/kernel/security/apparmor/profiles
chmod 000 /sys/kernel/security/apparmor/profiles
runner=(setpriv --reuid="$1" --regid="$2" --init-groups env
        HOME="$3" XDG_RUNTIME_DIR="$4" PATH="$5")
# Prove the same directory discovery + profile-read failure as the runner.
"${runner[@]}" bash -euc '
  test -d /sys/kernel/security/apparmor
  if head -c 1 /sys/kernel/security/apparmor/profiles; then exit 1; fi
'
"${runner[@]}" bash "$6" bash -euc '
  test "$(id -u)" = "$1"
  test "$(id -g)" = "$2"
  test ! -e /sys/kernel/security/apparmor
  findmnt -n -o OPTIONS /sys/kernel/security | grep -Eq "(^|,)ro(,|$)"
  if touch /sys/kernel/security/escape; then exit 1; fi
  grep -Eq "^CapEff:[[:space:]]+0+$" /proc/self/status
' bash "$1" "$2"
# The wrapper must not hide or replace the caller namespace's mount.
test -e /sys/kernel/security/apparmor/profiles
findmnt -n -o SOURCE /sys/kernel/security | grep -qx lane-fixture
""",
            "bash",
            str(os.getuid()),
            str(os.getgid()),
            str(Path.home()),
            os.environ["XDG_RUNTIME_DIR"],
            os.environ["PATH"],
            str(wrapper),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert Path("/proc/self/mountinfo").read_text() == original_mounts
