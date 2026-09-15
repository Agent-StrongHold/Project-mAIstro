"""Host path authorization for sandbox mounts and file transfer.

The sandbox owns only an explicitly allowlisted workspace root.  Resolution
alone is not enough: a symlink can change between a check and a host-side
open, so file transfer walks directory file descriptors with ``O_NOFOLLOW``.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path, PurePosixPath

# These are host roots intentionally admitted for ephemeral work.  A caller
# cannot turn an arbitrary service path into a sandbox mount by supplying it in
# SandboxConfig.writable_paths.
AUTHORIZED_HOST_ROOTS = (
    Path("/tmp/maistro-workspace"),  # nosec B108 - authorization root
    Path("/private/tmp/maistro-workspace"),  # nosec B108 - macOS temp root
    Path(tempfile.gettempdir()) / "maistro-workspace",  # nosec B108 - platform temp root
    Path("/repos"),
)


def validate_host_root(path: str | Path, *, create: bool = False) -> Path:
    """Return an authorized, non-symlink host root or raise ``ValueError``."""
    candidate = Path(path)
    if candidate.is_symlink():
        raise ValueError(f"sandbox host root must not be a symlink: {path}")
    if create:
        candidate.mkdir(parents=True, exist_ok=True)
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ValueError(f"sandbox host root does not exist: {path}") from exc
    if not resolved.is_dir():
        raise ValueError(f"sandbox host root is not a directory: {path}")
    allowed = tuple(root.resolve() for root in AUTHORIZED_HOST_ROOTS)
    if not any(resolved == root or root in resolved.parents for root in allowed):
        raise ValueError(f"sandbox host root is not authorized: {path}")
    return resolved


def _relative_parts(path: str, *, mount: str = "/work") -> tuple[str, ...]:
    """Parse a guest path without allowing lexical traversal."""
    guest = PurePosixPath(path.replace("\\", "/"))
    if guest.is_absolute():
        try:
            guest = guest.relative_to(mount)
        except ValueError as exc:
            raise ValueError(f"path {path!r} is outside sandbox mount {mount!r}") from exc
    if any(part in ("", ".", "..") for part in guest.parts):
        if ".." in guest.parts:
            raise ValueError(f"path {path!r} escapes sandbox root")
        guest = PurePosixPath(*[part for part in guest.parts if part != "."])
    if not guest.parts:
        raise ValueError("sandbox path must name a file")
    return guest.parts


def _open_parent(root: Path, parts: tuple[str, ...], *, create: bool) -> tuple[int, str]:
    """Open a path's parent beneath ``root`` without following symlinks."""
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            try:
                next_fd = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=fd,
                )
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(part, mode=0o700, dir_fd=fd)
                next_fd = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=fd,
                )
            os.close(fd)
            fd = next_fd
        return fd, parts[-1]
    except BaseException:
        os.close(fd)
        raise


def read_beneath(root: Path, path: str) -> bytes:
    parts = _relative_parts(path)
    parent_fd, name = _open_parent(root, parts, create=False)
    try:
        file_fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
        with os.fdopen(file_fd, "rb") as stream:
            return stream.read()
    finally:
        os.close(parent_fd)


def write_beneath(root: Path, path: str, content: bytes) -> None:
    parts = _relative_parts(path)
    parent_fd, name = _open_parent(root, parts, create=True)
    try:
        file_fd = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent_fd,
        )
        with os.fdopen(file_fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(parent_fd)


__all__ = ["AUTHORIZED_HOST_ROOTS", "read_beneath", "validate_host_root", "write_beneath"]
