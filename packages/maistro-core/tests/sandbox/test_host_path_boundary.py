"""Filesystem-boundary tests for the bubblewrap host authority (#1198)."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

import maistro.sandbox.paths as sandbox_paths
from maistro.sandbox.backends.bubblewrap import BubblewrapSandboxBackend
from maistro.sandbox.paths import read_beneath, validate_host_root, write_beneath
from maistro.sandbox.protocol import SandboxConfig


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


def test_guest_readable_widening_covers_the_written_chain(tmp_path: Path) -> None:
    """Kata's virtiofs share enforces host mode bits against the guest's id
    mapping, so the 0700/0600 transfer defaults are invisible to guest root.
    The widening opens exactly the written chain — file and provisioned
    parents — through the same no-follow walk, and nothing else (#76)."""
    from maistro.sandbox.paths import make_beneath_guest_readable

    root = tmp_path / "work"
    root.mkdir()
    outside = tmp_path / "outside-secret"
    outside.write_bytes(b"host-only")

    write_beneath(root, "new/nested/leaf", b"created")
    (root / "kept").write_bytes(b"untouched")
    os.chmod(root / "kept", 0o600)

    # The Kata backend hands over an inherited workdir descriptor, not a
    # path; widen through the fd the way the backend does.
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        make_beneath_guest_readable(fd, "new/nested/leaf", mount="/work")
    finally:
        os.close(fd)

    assert ((root / "new").stat().st_mode & 0o777) == 0o755
    assert ((root / "new" / "nested").stat().st_mode & 0o777) == 0o755
    leaf_mode = (root / "new" / "nested" / "leaf").stat().st_mode
    assert stat.S_IMODE(leaf_mode) == 0o644
    assert (root / "new" / "nested" / "leaf").read_bytes() == b"created"
    # Sibling writes keep their private mode; widening is per-write.
    assert stat.S_IMODE((root / "kept").stat().st_mode) == 0o600
    assert outside.read_bytes() == b"host-only"


def test_guest_readable_widening_refuses_a_swapped_symlink(tmp_path: Path) -> None:
    """A symlink swapped onto the written path after the transfer aborts the
    widening with the kernel's own error — the mode change must not follow it
    onto a host object outside the sandbox root (#76)."""
    from maistro.sandbox.paths import make_beneath_guest_readable

    root = tmp_path / "work"
    root.mkdir()
    outside = tmp_path / "outside-secret"
    outside.write_bytes(b"host-only")
    os.chmod(outside, 0o600)

    write_beneath(root, "leaf", b"created")
    (root / "leaf").unlink()
    (root / "leaf").symlink_to(outside)

    with pytest.raises(OSError):
        make_beneath_guest_readable(root, "leaf", mount="/work")
    assert stat.S_IMODE(outside.stat().st_mode) == 0o600
    assert outside.read_bytes() == b"host-only"


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
