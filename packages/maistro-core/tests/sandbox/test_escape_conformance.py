"""What the real backend actually contains, asked of the real kernel (#80).

`test_real_backend.py` asserts which flags `bwrap` is given, because that is
this repository's security content and it can be checked on a machine with no
bubblewrap at all. This file asks the other question: with those flags, what
can a workload inside the sandbox actually reach? Every expectation below was
measured against a live sandbox before it was written down — several of them
corrected a guess.

ADR-093 is explicit that Tier 3 is a guardrail against accidents and
prompt-injection mistakes, **not** a boundary against hostile code: a
user-namespace sandbox still exposes the full host syscall surface, and this
suite does not pretend otherwise. What it establishes is that the guardrail is
real and stays real — that the filesystem, process, device, socket, credential
and privilege surfaces are what the support matrix says, so a regression in the
flags shows up as a failing test rather than as an incident.

Split the same way as its sibling: what is a pure function of the config is
asserted everywhere; what needs a kernel is asserted where a kernel will build
the namespace.
"""

from __future__ import annotations

import asyncio
import resource
from pathlib import Path

import pytest

from maistro.sandbox import SandboxConfig, detect_host_capabilities
from maistro.sandbox.backends.bubblewrap import BubblewrapSandboxBackend, resource_limits

HAS_BWRAP = detect_host_capabilities().supports("bubblewrap")
requires_bwrap = pytest.mark.skipif(
    HAS_BWRAP is False, reason="this host cannot build a bubblewrap sandbox"
)


@pytest.fixture
async def sandbox(tmp_path: Path):
    """A live sandbox, torn down whatever the test does to it."""
    backend = BubblewrapSandboxBackend(root=tmp_path)
    instance = await backend.spawn(
        config=SandboxConfig(memory_mb=128, cpu_cores=0.05, timeout_s=20, max_file_mb=8)
    )
    try:
        yield backend, instance
    finally:
        await backend.destroy(instance)


async def run(sandbox, script: str, timeout_s: int = 30):
    backend, instance = sandbox
    return await backend.exec(instance, ["sh", "-c", script], timeout_s=timeout_s)


async def output(sandbox, script: str, timeout_s: int = 30) -> str:
    result = await run(sandbox, script, timeout_s)
    return (result.stdout + result.stderr).strip()


def workdir_of(root: Path, instance) -> Path | None:
    """The sandbox's host directory.

    `mkdtemp` appends its own suffix to the instance id, so `root / id` is a
    path that never exists — and a cleanup test asserting *that* had gone away
    would pass without the backend deleting anything.
    """
    found = list(root.glob(f"{instance.id}-*"))
    assert len(found) < 2, f"more than one workdir for {instance.id}"
    return found[0] if found else None


# --- the budgets, as values ---------------------------------------------------
#
# `memory_mb` and `cpu_cores` were declared on SandboxConfig and applied by
# nothing. A budget the runtime ignores is worse than no budget, because the
# caller believes it has one.


def test_the_declared_memory_budget_becomes_a_real_limit() -> None:
    limits = resource_limits(SandboxConfig(memory_mb=256))

    assert limits[resource.RLIMIT_AS] == (256 * 1024 * 1024,) * 2


def test_cpu_cores_is_a_rate_spent_over_the_timeout() -> None:
    """A quarter core for 120 seconds is 30 CPU-seconds. Reading `cpu_cores`
    as anything else leaves it meaning nothing an rlimit can express."""
    limits = resource_limits(SandboxConfig(cpu_cores=0.25, timeout_s=120))

    assert limits[resource.RLIMIT_CPU][0] == 30 + 2  # the documented grace


def test_a_file_size_ceiling_protects_the_host_disk() -> None:
    """The workdir is a host directory. Without this a workload fills the
    host's filesystem while never leaving its own sandbox."""
    limits = resource_limits(SandboxConfig(max_file_mb=8))

    assert limits[resource.RLIMIT_FSIZE] == (8 * 1024 * 1024,) * 2


def test_a_zero_budget_does_not_become_an_unlimited_one() -> None:
    """`setrlimit(0)` is a legal value that stops the workload dead, and
    arithmetic that produced it from a rounding error would look like a
    tightened limit rather than a broken sandbox."""
    limits = resource_limits(SandboxConfig(memory_mb=0, cpu_cores=0.0, max_file_mb=0))

    assert all(soft > 0 for soft, _hard in limits.values())


# --- resource exhaustion, against the kernel ---------------------------------


@requires_bwrap
async def test_a_memory_hog_is_refused_rather_than_served(sandbox) -> None:
    result = await run(
        sandbox,
        "python3 -c 'b=bytearray(1024*1024*1024)' 2>&1 | grep -c MemoryError",
    )

    assert result.stdout.strip() == "1"


@requires_bwrap
async def test_a_workload_cannot_write_a_file_larger_than_its_ceiling(sandbox) -> None:
    text = await output(sandbox, "dd if=/dev/zero of=/work/big bs=1M count=64 2>&1 | tail -1")

    assert "File size limit exceeded" in text


@requires_bwrap
async def test_a_busy_loop_is_killed_by_the_cpu_budget(sandbox) -> None:
    """Not by the wall-clock timeout — the exec below is given far longer than
    the CPU budget, so a pass here means the kernel stopped it."""
    result = await run(sandbox, "while :; do :; done", timeout_s=30)

    assert result.timed_out is False
    assert result.exit_code != 0


@requires_bwrap
async def test_ordinary_work_still_runs_under_all_of_them(sandbox) -> None:
    """The limits are only worth having if they do not break the sandbox for
    the work it exists to run."""
    result = await run(sandbox, "echo hello")

    assert result.exit_code == 0
    assert result.stdout.strip() == "hello"


# --- filesystem ---------------------------------------------------------------


@requires_bwrap
async def test_the_host_password_file_is_not_there_to_read(sandbox) -> None:
    text = await output(sandbox, "cat /etc/passwd")

    assert "No such file" in text


@requires_bwrap
async def test_host_home_directories_are_absent(sandbox) -> None:
    text = await output(sandbox, "ls /home")

    assert "No such file" in text


@requires_bwrap
async def test_the_runtime_directories_the_sandbox_needs_are_read_only(sandbox) -> None:
    """`/usr` has to be there for an interpreter to exist at all, which is why
    it is bound rather than absent — so the property that matters is that it
    cannot be written."""
    text = await output(sandbox, "touch /usr/escape 2>&1")

    assert "Read-only file system" in text


@requires_bwrap
async def test_the_only_writable_host_path_is_the_workdir(sandbox, tmp_path: Path) -> None:
    """The sandbox's own `/` and `/tmp` are writable tmpfs and vanish with it;
    what must not happen is a write that outlives the sandbox anywhere but
    here."""
    _backend, instance = sandbox
    await run(sandbox, "echo written > /work/proof; echo transient > /escape")

    workdir = workdir_of(tmp_path, instance)
    assert workdir is not None
    assert (workdir / "proof").read_text().strip() == "written"
    assert not (tmp_path / "escape").exists()


@requires_bwrap
async def test_pid_one_is_the_sandbox_not_the_host(sandbox) -> None:
    """`/proc/1/root` is the classic way out of a half-built container."""
    text = await output(sandbox, "ls /proc/1/root/etc/passwd 2>&1")

    assert "No such file" in text


# --- process and namespace ----------------------------------------------------


@requires_bwrap
async def test_the_sandbox_sees_only_its_own_processes(sandbox) -> None:
    count = await output(sandbox, "ls /proc | grep -c '^[0-9]*$'")

    # Its own shell, the `ls`, the pipeline. A host's process table is orders
    # of magnitude larger; the assertion is about the order, not the exact
    # number, which depends on how the shell forks the pipeline.
    assert int(count) < 10


@requires_bwrap
async def test_a_nested_user_namespace_cannot_be_mapped(sandbox) -> None:
    """Writing a uid_map inside is how a workload would try to get back the
    capabilities `--cap-drop ALL` took away."""
    text = await output(sandbox, "unshare -Ur true 2>&1")

    assert "Operation not permitted" in text or "not permitted" in text


@requires_bwrap
async def test_chroot_is_refused(sandbox) -> None:
    text = await output(sandbox, "chroot / /bin/true 2>&1")

    assert "Operation not permitted" in text


@requires_bwrap
async def test_the_workload_cannot_mount_anything(sandbox) -> None:
    text = await output(sandbox, "mkdir -p /work/m && mount -t tmpfs none /work/m 2>&1")

    assert "denied" in text or "permitted" in text


# --- devices ------------------------------------------------------------------


@requires_bwrap
async def test_no_block_device_is_reachable(sandbox) -> None:
    """A visible disk is a filesystem escape that needs no kernel bug."""
    text = await output(sandbox, "ls /dev/sd* /dev/nvme* /dev/vd* /dev/loop* 2>&1")

    assert "No such file" in text
    assert not [line for line in text.splitlines() if not line.startswith("ls:")]


@requires_bwrap
async def test_the_virtualization_device_is_not_exposed(sandbox) -> None:
    result = await run(sandbox, "test -e /dev/kvm")

    assert result.exit_code != 0


@requires_bwrap
async def test_new_devices_cannot_be_created(sandbox) -> None:
    text = await output(sandbox, "mknod /work/disk b 8 0 2>&1")

    assert "Operation not permitted" in text


# --- host sockets -------------------------------------------------------------


@requires_bwrap
async def test_no_host_unix_socket_is_visible(sandbox) -> None:
    """A reachable `docker.sock` or agent socket is root on the host, with no
    exploit required."""
    lines = await output(sandbox, "cat /proc/net/unix 2>/dev/null | wc -l")

    assert int(lines) <= 1  # the header, and nothing else


@requires_bwrap
async def test_the_host_container_socket_is_absent(sandbox) -> None:
    text = await output(sandbox, "ls /var/run/docker.sock /run/docker.sock 2>&1")

    assert "No such file" in text


@requires_bwrap
async def test_no_host_listening_port_is_visible(sandbox) -> None:
    """`/proc/net/tcp` is per network namespace, so an empty one is the
    namespace being real rather than the host having no services."""
    lines = await output(sandbox, "cat /proc/net/tcp 2>/dev/null | wc -l")

    assert int(lines) <= 1


# --- credentials --------------------------------------------------------------


@requires_bwrap
async def test_the_environment_holds_only_what_the_config_put_there(
    tmp_path: Path,
) -> None:
    """`--clearenv` is the flag; this is the consequence. An inherited
    environment is how an API key reaches candidate code without anyone
    passing it."""
    backend = BubblewrapSandboxBackend(root=tmp_path)
    instance = await backend.spawn(config=SandboxConfig(env={"GIVEN": "yes"}))
    try:
        result = await backend.exec(instance, ["sh", "-c", "env"], timeout_s=20)
    finally:
        await backend.destroy(instance)

    names = {line.split("=", 1)[0] for line in result.stdout.splitlines() if "=" in line}
    # PWD is set by the shell itself, not inherited.
    assert names <= {"GIVEN", "PWD"}


# --- privilege ----------------------------------------------------------------


@requires_bwrap
async def test_every_capability_is_dropped(sandbox) -> None:
    text = await output(sandbox, "grep CapEff /proc/self/status")

    assert text.split()[-1].strip("0") == ""


@requires_bwrap
async def test_setuid_binaries_are_visible_but_cannot_escalate(sandbox) -> None:
    """`/usr` is bound read-only, so `sudo` and `su` are *there*. What stops
    them is `no_new_privs`, which the kernel applies to the whole subtree — so
    the property to assert is the flag, not the absence of the files."""
    text = await output(sandbox, "grep NoNewPrivs /proc/self/status")

    assert text.split()[-1] == "1"


# --- timeout, kill and cleanup ------------------------------------------------


@requires_bwrap
async def test_a_timeout_leaves_nothing_running(tmp_path: Path) -> None:
    """`--die-with-parent` is what makes the kill reach the sandbox rather than
    only `bwrap`. A sandbox that outlived its timeout would still hold the
    workdir the next line deletes."""
    backend = BubblewrapSandboxBackend(root=tmp_path)
    instance = await backend.spawn(config=SandboxConfig(timeout_s=1))

    assert workdir_of(tmp_path, instance) is not None

    result = await backend.exec(instance, ["sh", "-c", "sleep 30"], timeout_s=1)
    await backend.destroy(instance)
    await asyncio.sleep(0.2)

    assert result.timed_out is True
    assert workdir_of(tmp_path, instance) is None


@requires_bwrap
async def test_the_workdir_is_gone_after_destroy_even_with_files_in_it(sandbox, tmp_path) -> None:
    backend, instance = sandbox
    await run(sandbox, "mkdir -p /work/deep/tree && echo x > /work/deep/tree/file")
    assert workdir_of(tmp_path, instance) is not None

    await backend.destroy(instance)

    assert workdir_of(tmp_path, instance) is None
