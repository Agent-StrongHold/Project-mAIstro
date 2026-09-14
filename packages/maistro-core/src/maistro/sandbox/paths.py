"""Positive host-path authority and race-resistant sandbox file transfer.

Host paths are capabilities, not caller-selected strings. Mounts are accepted
only below explicit scratch/repository roots, and symlink targets must remain
inside the same root. Host-side file transfer walks directory descriptors with
``O_NOFOLLOW`` so validation and the final open share one kernel-owned path.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterable
from contextlib import suppress
from pathlib import Path, PurePosixPath

# These are deployment-owned roots for ephemeral workspace mounts. A backend
# may add its own explicitly supplied workspace root as another capability.
AUTHORIZED_HOST_ROOTS = (
    Path("/tmp/maistro-workspace"),  # nosec B108 - deliberate workspace root
    Path("/private/tmp/maistro-workspace"),  # nosec B108 - macOS workspace root
    Path(tempfile.gettempdir()) / "maistro-workspace",  # nosec B108 - platform root
    Path("/repos"),
)

# Broad or security-sensitive roots are never useful writable mount roots. A
# narrower child can still be authorized explicitly.
_SENSITIVE_ROOTS = {
    Path("/"),
    Path("/tmp"),
    Path("/private/tmp"),
    Path("/home"),
    Path("/root"),
    Path("/etc"),
    Path("/proc"),
    Path("/sys"),
    Path("/dev"),
    Path("/run"),
    Path("/var/run"),
}
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def _canonical_allowed_roots(extra_roots: Iterable[str | Path] = ()) -> tuple[Path, ...]:
    roots: list[Path] = []
    for raw in (*AUTHORIZED_HOST_ROOTS, *extra_roots):
        root = Path(raw)
        try:
            resolved = root.resolve(strict=True)
        except FileNotFoundError:
            # A configured deployment root may not exist until its workspace is
            # provisioned. It cannot authorize a mount until it does exist.
            continue
        if not resolved.is_dir():
            continue
        if resolved in _SENSITIVE_ROOTS:
            raise ValueError(f"sandbox writable root is too broad or sensitive: {root}")
        if resolved not in roots:
            roots.append(resolved)
    return tuple(roots)


def validate_host_root(
    path: str | Path,
    *,
    create: bool = False,
    allowed_roots: Iterable[str | Path] = (),
) -> Path:
    """Return a canonical authorized directory or raise ``ValueError``.

    A symlink at the requested path is refused. Symlink components are allowed
    only when their resolved target remains beneath an authorized root. The
    returned canonical path is what the mount builder uses, so it does not
    hand a later operation the original symlink spelling.
    """
    candidate = Path(path)
    if not str(path) or "\x00" in str(path) or "\\" in str(path):
        raise ValueError(f"sandbox host root has an invalid path: {path!r}")
    if not candidate.is_absolute():
        raise ValueError(f"sandbox host root must be absolute: {path!r}")
    if candidate.is_symlink():
        raise ValueError(f"sandbox host root must not be a symlink: {path}")

    roots = _canonical_allowed_roots(allowed_roots)
    if not roots:
        raise ValueError(f"sandbox host root has no host-owned authorization: {path}")

    try:
        resolved = candidate.resolve(strict=create)
    except FileNotFoundError as exc:
        raise ValueError(f"sandbox host root does not exist: {path}") from exc

    if not any(resolved == root or root in resolved.parents for root in roots):
        raise ValueError(f"sandbox host root is not authorized: {path}")
    if create:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise ValueError(f"sandbox host root could not be created: {path}") from exc
    if not resolved.is_dir():
        raise ValueError(f"sandbox host root is not a directory: {path}")
    return resolved


def authorized_host_mounts(
    paths: Iterable[str], *, allowed_roots: Iterable[str | Path] = ()
) -> tuple[Path, ...]:
    """Canonicalize all requested mounts under the host-owned root policy."""
    requested = tuple(paths)
    if not requested:
        return ()
    return tuple(validate_host_root(path, allowed_roots=allowed_roots) for path in requested)


def _relative_parts(path: str, *, mount: str = "/work") -> tuple[str, ...]:
    """Parse a guest path without allowing lexical traversal or host paths."""
    if not isinstance(path, str) or not path or "\x00" in path or "\\" in path:
        raise ValueError(f"invalid sandbox path: {path!r}")
    guest = PurePosixPath(path)
    if guest.is_absolute():
        try:
            guest = guest.relative_to(mount)
        except ValueError as exc:
            raise ValueError(f"path {path!r} is outside sandbox mount {mount!r}") from exc
    if ".." in guest.parts:
        raise ValueError(f"path {path!r} escapes sandbox root")
    parts = tuple(part for part in guest.parts if part not in ("", "."))
    if not parts:
        raise ValueError("sandbox path must name a file")
    return parts


def _open_parent(root: Path | int, parts: tuple[str, ...], *, create: bool) -> tuple[int, str]:
    """Open each parent beneath ``root`` without following a symlink."""
    if not _NOFOLLOW or not hasattr(os, "O_DIRECTORY") or not hasattr(os, "open"):
        raise OSError("descriptor-relative no-follow file access is unavailable")
    # A backend keeps the workdir descriptor for the instance lifetime. Duplicating
    # it gives this operation ownership without reopening a raceable pathname.
    fd = (
        os.dup(root)
        if isinstance(root, int)
        else os.open(root, os.O_RDONLY | os.O_DIRECTORY | _NOFOLLOW)
    )
    if isinstance(root, int):
        os.set_inheritable(fd, False)
    try:
        for part in parts[:-1]:
            try:
                next_fd = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | _NOFOLLOW,
                    dir_fd=fd,
                )
            except FileNotFoundError:
                if not create:
                    raise
                # A concurrent creator may win; the no-follow open below
                # still decides whether its object is acceptable.
                with suppress(FileExistsError):
                    os.mkdir(part, mode=0o700, dir_fd=fd)
                next_fd = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | _NOFOLLOW,
                    dir_fd=fd,
                )
            os.close(fd)
            fd = next_fd
        return fd, parts[-1]
    except BaseException:
        os.close(fd)
        raise


def read_beneath(root: Path | int, path: str) -> bytes:
    """Read a regular path beneath ``root`` without following symlinks."""
    parts = _relative_parts(path)
    parent_fd, name = _open_parent(root, parts, create=False)
    try:
        file_fd = os.open(name, os.O_RDONLY | _NOFOLLOW, dir_fd=parent_fd)
        with os.fdopen(file_fd, "rb") as stream:
            return stream.read()
    finally:
        os.close(parent_fd)


def write_beneath(root: Path | int, path: str, content: bytes) -> None:
    """Replace a file beneath ``root`` without following a swapped symlink."""
    parts = _relative_parts(path)
    parent_fd, name = _open_parent(root, parts, create=True)
    try:
        file_fd = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC | _NOFOLLOW,
            0o600,
            dir_fd=parent_fd,
        )
        with os.fdopen(file_fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(parent_fd)


__all__ = [
    "AUTHORIZED_HOST_ROOTS",
    "authorized_host_mounts",
    "read_beneath",
    "validate_host_root",
    "write_beneath",
]
