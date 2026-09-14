"""Filesystem-boundary tests for the bubblewrap host authority (#1198)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

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
