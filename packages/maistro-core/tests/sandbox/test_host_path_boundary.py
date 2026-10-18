"""Filesystem-boundary tests for the bubblewrap host authority (#1198)."""

from __future__ import annotations

import asyncio
import os
import threading
import time
from contextlib import suppress
from pathlib import Path

import pytest

import maistro.sandbox.backends.bubblewrap as bubblewrap_module
import maistro.sandbox.paths as sandbox_paths
from maistro.sandbox.backends.bubblewrap import BubblewrapSandboxBackend
from maistro.sandbox.paths import read_beneath, validate_host_root, write_beneath
from maistro.sandbox.protocol import SandboxConfig, SandboxInstance


def _backend(root: Path) -> BubblewrapSandboxBackend:
    return BubblewrapSandboxBackend(root=root, bwrap="/usr/bin/bwrap")


def test_writable_mounts_require_a_positive_host_owned_root(tmp_path: Path) -> None:
    allowed = tmp_path / "scratch"
    allowed.mkdir()
    backend = _backend(tmp_path)

    argv = backend.build_argv(
        SandboxConfig(writable_paths=[str(allowed)]),
        tmp_path,
        ["true"],
    )

    assert str(allowed) in argv
    assert "/work-extra-0" in argv


@pytest.mark.parametrize(
    "path",
    [
        "/",
        str(Path.home()),
        "/repo/.env",
        "/var/run/docker.sock",
        "/run/docker.sock",
        "/etc/passwd",
        "/tmp/../etc/passwd",
    ],
)
def test_sensitive_and_traversal_mounts_are_denied(tmp_path: Path, path: str) -> None:
    with pytest.raises(ValueError):
        _backend(tmp_path).build_argv(SandboxConfig(writable_paths=[path]), tmp_path, ["true"])


async def test_spawn_rejects_an_unauthorized_mount_before_exposing_an_instance(
    tmp_path: Path,
) -> None:
    backend = _backend(tmp_path)

    with pytest.raises(ValueError):
        await backend.spawn(config=SandboxConfig(writable_paths=["/etc"]))

    assert not list(tmp_path.glob("bwrap-*"))


def test_mount_symlink_to_outside_is_denied(tmp_path: Path) -> None:
    allowed = tmp_path / "scratch"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    link = allowed / "outside-link"
    link.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        validate_host_root(link, allowed_roots=(tmp_path,))


def test_host_root_spellings_that_cannot_be_authorized_are_refused(
    tmp_path: Path,
) -> None:
    """Empty, NUL, backslash, and relative spellings are denied before any
    resolution, so policy is decided on canonical paths only."""
    for spelling in ("", "null\x00byte", "back\\slash"):
        with pytest.raises(ValueError, match="invalid path"):
            validate_host_root(spelling)
    with pytest.raises(ValueError, match="must be absolute"):
        validate_host_root("relative/child", allowed_roots=(tmp_path,))


def test_an_allowed_root_may_not_itself_be_sensitive(tmp_path: Path) -> None:
    """Positive authorization cannot delegate a broad root: declaring ``/``
    (or any denylisted root) as an allowed root is refused outright."""
    with pytest.raises(ValueError, match="too broad or sensitive"):
        validate_host_root(tmp_path / "scratch", allowed_roots=("/",))


def test_allowed_roots_that_do_not_exist_or_are_not_directories_authorize_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A configured root must exist as a directory before it can authorize a
    mount; a missing or file-shaped root fails closed. Default deployment
    roots are cleared so the candidate cannot fall under any other root."""
    monkeypatch.setattr(sandbox_paths, "AUTHORIZED_HOST_ROOTS", ())
    plain_file = tmp_path / "not-a-root"
    plain_file.write_bytes(b"data")
    with pytest.raises(ValueError, match="no host-owned authorization"):
        validate_host_root(tmp_path / "scratch", allowed_roots=(plain_file,))

    missing = tmp_path / "never-provisioned"
    with pytest.raises(ValueError, match="no host-owned authorization"):
        validate_host_root(tmp_path / "scratch", allowed_roots=(missing,))


def test_create_mode_pins_its_documented_fail_closed_contract(tmp_path: Path) -> None:
    """``create=True`` provisions an existing directory entry and refuses
    everything else: a not-yet-existing path raises before any mkdir (it
    cannot create roots that were never authorized into existence), and a
    file-shaped entry raises instead of being adopted as a root."""
    allowed = tmp_path / "scratch"
    allowed.mkdir()

    with pytest.raises(ValueError, match="does not exist"):
        validate_host_root(allowed / "session", allowed_roots=(allowed,), create=True)
    with pytest.raises(ValueError, match="not a directory"):
        validate_host_root(allowed / "session", allowed_roots=(allowed,))

    (allowed / "plain-file").write_bytes(b"data")
    with pytest.raises(ValueError, match="not a directory"):
        validate_host_root(allowed / "plain-file", allowed_roots=(allowed,))
    with pytest.raises(ValueError, match="could not be created"):
        validate_host_root(allowed / "plain-file", allowed_roots=(allowed,), create=True)

    (allowed / "session").mkdir()
    provisioned = validate_host_root(allowed / "session", allowed_roots=(allowed,), create=True)
    assert provisioned == (allowed / "session").resolve(strict=True)
    assert provisioned.is_dir()


def test_host_transfer_rejects_spellings_that_name_no_file(tmp_path: Path) -> None:
    root = tmp_path / "work"
    root.mkdir()

    for path in ("", "/work", "/work/."):
        with pytest.raises(ValueError):
            write_beneath(root, path, b"blocked")
        with pytest.raises(ValueError):
            read_beneath(root, path)


def test_host_transfer_walks_nested_components_without_following_symlinks(
    tmp_path: Path,
) -> None:
    """Multi-component guest paths walk one directory descriptor per
    component with ``O_NOFOLLOW``; a symlinked middle component cannot be
    substituted for a directory."""
    root = tmp_path / "work"
    (root / "sub").mkdir(parents=True)
    (root / "sub" / "leaf").write_bytes(b"payload")

    assert read_beneath(root, "sub/leaf") == b"payload"
    write_beneath(root, "sub/leaf", b"updated")
    assert (root / "sub" / "leaf").read_bytes() == b"updated"

    # A directory symlink where a walk component belongs cannot be opened:
    # O_NOFOLLOW makes the substitution fail with the kernel's own error.
    swapped_root = tmp_path / "swapped"
    swapped_root.mkdir()
    (swapped_root / "escape").symlink_to(tmp_path)
    with pytest.raises(OSError):
        read_beneath(swapped_root, "escape/leaf")


def test_host_transfer_read_refuses_a_missing_intermediate_component(
    tmp_path: Path,
) -> None:
    root = tmp_path / "work"
    root.mkdir()

    with pytest.raises(FileNotFoundError):
        read_beneath(root, "missing/leaf")
    assert not (root / "missing").exists()  # read never provisions


def test_host_transfer_write_creates_missing_intermediate_directories(
    tmp_path: Path,
) -> None:
    """Writing a nested path provisions its parent directories with a
    private mode inside the authorized root — the only growth a write may
    cause."""
    root = tmp_path / "work"
    root.mkdir()

    write_beneath(root, "new/nested/leaf", b"created")
    assert (root / "new" / "nested" / "leaf").read_bytes() == b"created"
    assert ((root / "new").stat().st_mode & 0o777) == 0o700
    assert ((root / "new" / "nested").stat().st_mode & 0o777) == 0o700


def test_host_transfer_walk_failure_surfaces_the_os_error_and_leaves_no_descriptor(
    tmp_path: Path,
) -> None:
    """A walk component that exists but is not a directory aborts the walk
    with the kernel's own error, after closing the in-flight descriptor."""
    root = tmp_path / "work"
    root.mkdir()
    (root / "plain").write_bytes(b"file where a component belongs")

    proc_fds = Path("/proc/self/fd")
    before = set(os.listdir(proc_fds)) if proc_fds.is_dir() else None
    with pytest.raises(NotADirectoryError):
        read_beneath(root, "plain/leaf")
    if before is not None:
        # The aborted walk must not leak its in-flight directory descriptor.
        assert not set(os.listdir(proc_fds)) - before


def test_host_transfer_fails_closed_without_nofollow_support(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On a platform without ``O_NOFOLLOW`` the descriptor-relative walk
    refuses to operate rather than silently losing its race resistance."""
    root = tmp_path / "work"
    root.mkdir()
    monkeypatch.setattr(sandbox_paths, "_NOFOLLOW", 0)

    with pytest.raises(OSError, match="no-follow"):
        read_beneath(root, "leaf")
    with pytest.raises(OSError, match="no-follow"):
        write_beneath(root, "leaf", b"x")


def test_symlinked_parent_is_allowed_only_when_resolution_stays_inside(tmp_path: Path) -> None:
    allowed = tmp_path / "scratch"
    target = allowed / "nested"
    allowed.mkdir()
    target.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(allowed, target_is_directory=True)

    assert validate_host_root(alias / "nested", allowed_roots=(tmp_path,)) == target


def test_host_file_transfer_rejects_parent_traversal_and_docker_socket_paths(
    tmp_path: Path,
) -> None:
    root = tmp_path / "work"
    root.mkdir()

    for path in ("../escape", "/work/../../etc/passwd", "/var/run/docker.sock"):
        with pytest.raises(ValueError):
            write_beneath(root, path, b"blocked")


def test_host_file_transfer_does_not_follow_a_symlink_to_a_repo_secret(tmp_path: Path) -> None:
    root = tmp_path / "work"
    root.mkdir()
    secret = tmp_path / "repo-secret"
    secret.write_bytes(b"secret")
    (root / "result").symlink_to(secret)

    with pytest.raises(OSError):
        write_beneath(root, "result", b"overwritten")
    with pytest.raises(OSError):
        read_beneath(root, "result")
    assert secret.read_bytes() == b"secret"


def test_final_open_cannot_be_swapped_to_an_outside_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "work"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.write_bytes(b"host secret")
    target = root / "result"
    target.write_bytes(b"old")

    original_open = os.open
    swapped = False

    def swap_before_final_open(
        path: object, flags: int, mode: int = 0o777, *, dir_fd: int | None = None
    ) -> int:
        nonlocal swapped
        if path == "result" and dir_fd is not None and not swapped:
            swapped = True
            target.unlink()
            target.symlink_to(outside)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    import maistro.sandbox.paths as paths

    monkeypatch.setattr(paths.os, "open", swap_before_final_open)
    with pytest.raises(OSError):
        write_beneath(root, "result", b"must not escape")

    assert outside.read_bytes() == b"host secret"
    assert swapped


async def test_backend_file_access_and_destroy_share_ownership_lock(tmp_path: Path) -> None:
    backend = _backend(tmp_path)
    instance = await backend.spawn(config=SandboxConfig())
    await backend.write_file(instance, "/work/result", b"safe")
    assert await backend.read_file(instance, "result") == b"safe"
    await backend.destroy(instance)
    with pytest.raises(KeyError):
        await backend.read_file(instance, "result")


class _BlockedTransferWorker:
    """Stop a transfer worker between submission and descriptor use.

    The double records the descriptor it was handed and blocks until the test
    releases it, so a test can cancel the submitting coroutine -- which
    releases the backend's per-instance ownership lock -- while the worker
    thread is still alive. Threads cannot be cancelled, exactly as in
    production. After release it records what its operation actually touched,
    so a test can pin the transfer to the workdir it was authorized against.
    """

    def __init__(self, mode: str, *, fail: bool = False) -> None:
        self._mode = mode
        self._fail = fail
        self.started = threading.Event()
        self.release = threading.Event()
        self.seen_fd: int | None = None
        self.performed_inode: int | None = None
        self.error: BaseException | None = None

    def __call__(self, fd: int, path: str, content: bytes = b"") -> object:
        self.seen_fd = fd
        self.started.set()
        if not self.release.wait(timeout=30):
            raise TimeoutError("test double was never released")
        try:
            if self._fail:
                raise OSError("transfer worker failed as the test directed")
            if self._mode == "write":
                write_beneath(fd, path, content)
                self.performed_inode = os.fstat(fd).st_ino
                return None
            payload = read_beneath(fd, path)
            self.performed_inode = os.fstat(fd).st_ino
            return payload
        except BaseException as exc:
            self.error = exc
            raise


async def _start_blocked_transfer(
    backend: BubblewrapSandboxBackend,
    instance: SandboxInstance,
    worker: _BlockedTransferWorker,
    *,
    write: bool,
) -> asyncio.Task[object]:
    """Start a transfer whose worker is blocked, and cancel its caller.

    Returns the cancelled task once the cancellation has been delivered -- the
    ownership lock is released while the worker is still alive, which is the
    state the descriptor-lifetime contract has to survive.
    """
    if write:
        task: asyncio.Task[object] = asyncio.create_task(
            backend.write_file(instance, "result", b"payload")
        )
    else:
        task = asyncio.create_task(backend.read_file(instance, "result"))
    # Yield to the loop while waiting: the submitting coroutine only runs when
    # the event loop gets a turn.
    deadline = time.monotonic() + 30
    while not worker.started.is_set():
        if time.monotonic() > deadline:  # pragma: no cover - scheduling guard
            worker.release.set()
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            pytest.fail("transfer worker never started")
        await asyncio.sleep(0.01)
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    return task


async def test_cancellation_during_transfer_keeps_the_workdir_descriptor_alive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Teardown may not close the workdir descriptor while a transfer worker
    whose caller was cancelled still holds it.

    A cancelled caller releases the ownership lock, but its worker keeps the
    descriptor it was handed. If destroy closed that descriptor (and the
    kernel reused the number) before the worker ran, the worker's
    descriptor-relative walk would silently operate on a directory the
    transfer was never authorized against. destroy therefore waits the
    worker out first, so the descriptor stays live -- and still referring to
    the checked workdir -- for the worker's whole lifetime.
    """
    backend = _backend(tmp_path)
    instance = await backend.spawn(config=SandboxConfig())
    worker = _BlockedTransferWorker("write")
    monkeypatch.setattr(bubblewrap_module, "write_beneath", worker)

    await _start_blocked_transfer(backend, instance, worker, write=True)

    _config, workdir, workdir_fd = backend._require(instance)
    workdir_inode = os.stat(workdir).st_ino
    assert worker.seen_fd == workdir_fd

    destroy_task = asyncio.create_task(backend.destroy(instance))
    # While the worker is still blocked, teardown must be waiting -- not
    # closing the descriptor or removing the workdir out from under it.
    for _ in range(50):
        await asyncio.sleep(0.01)
        assert os.fstat(workdir_fd).st_ino == workdir_inode
    assert not destroy_task.done()

    worker.release.set()
    await destroy_task
    assert not workdir.exists()
    # The workdir descriptor was closed exactly once, after the worker
    # finished: no descriptor anywhere still resolves into the removed tree.
    proc_fds = Path("/proc/self/fd")
    if proc_fds.is_dir():
        for entry in proc_fds.iterdir():
            with suppress(FileNotFoundError):
                # An entry can vanish between listing and readlink; only a
                # stable link into the removed tree would be a leak.
                assert not os.readlink(entry).startswith(str(workdir))


async def test_cancelled_transfer_still_lands_in_the_checked_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A write whose caller was cancelled still completes against the workdir
    it was granted -- not against whatever a reused descriptor number would
    point at."""
    backend = _backend(tmp_path)
    instance = await backend.spawn(config=SandboxConfig())
    worker = _BlockedTransferWorker("write")
    monkeypatch.setattr(bubblewrap_module, "write_beneath", worker)

    await _start_blocked_transfer(backend, instance, worker, write=True)

    _config, workdir, _workdir_fd = backend._require(instance)
    workdir_inode = os.stat(workdir).st_ino
    destroy_task = asyncio.create_task(backend.destroy(instance))
    worker.release.set()
    await destroy_task

    # The abandoned write ran to completion, into the authorized workdir, and
    # the worker saw no error even though teardown was racing it.
    assert worker.error is None
    assert worker.performed_inode == workdir_inode
    assert not workdir.exists()


async def test_cancellation_during_read_is_waited_out_by_teardown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The read path registers like the write path, and a transfer worker
    that fails after its caller was cancelled does not leave the instance
    half-destroyed: teardown waits it out, then completes."""
    backend = _backend(tmp_path)
    instance = await backend.spawn(config=SandboxConfig())
    await backend.write_file(instance, "result", b"payload")
    worker = _BlockedTransferWorker("read", fail=True)
    monkeypatch.setattr(bubblewrap_module, "read_beneath", worker)

    await _start_blocked_transfer(backend, instance, worker, write=False)

    _config, workdir, workdir_fd = backend._require(instance)
    workdir_inode = os.stat(workdir).st_ino
    destroy_task = asyncio.create_task(backend.destroy(instance))
    for _ in range(20):
        await asyncio.sleep(0.01)
        assert os.fstat(workdir_fd).st_ino == workdir_inode
    assert not destroy_task.done()
    worker.release.set()

    await destroy_task
    assert worker.error is not None  # the worker's failure was waited out
    assert not backend._inflight_transfers
    assert not backend._file_locks
    with pytest.raises(KeyError):
        await backend.read_file(instance, "result")
