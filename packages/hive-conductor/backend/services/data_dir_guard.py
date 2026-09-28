"""Refuse to boot on a data directory that cannot keep its persistence promise.

``CONDUCTOR_DATA_DIR`` holds everything the Conductor must survive a restart
with: the SQLite state database (accounts, sessions, settings, registration
policy), the age vault and its identity key, and the encrypted user
credential store. Issue #331's contract is that a deployment asking for
persistence gets it or gets a refusal — never a Conductor that starts,
accepts logins and provisions accounts, and throws all of it away on the
next ``docker compose down/up`` or image replacement.

Two refusals, both fail-closed before any subsystem touches the directory:

- **DATA_DIR_UNWRITABLE** — the directory cannot be created or written by
  this process (wrong volume ownership, read-only mount, missing host
  directory). The alternative is failing later, mid-flight, in whatever
  subsystem touches the filesystem first — or worse, an ephemeral in-memory
  fallback serving an empty registry as a fresh public first-run window
  (ADR-072: state unavailability must stop the API, not rebind it).

- **DATA_DIR_EPHEMERAL** — the process is running inside a container and the
  configured data directory is *not* a mounted filesystem. Container
  filesystem state is discarded on recreate, so any account, session,
  setting, or vault entry written there is already lost. This is exactly the
  shape issue #331 closed: a deployment that looked configured but was
  silently ephemeral. The check runs only inside a container because a bare
  ``uvicorn`` on a host keeps state fine in a plain directory like
  ``~/.conductor``.

``CONDUCTOR_ALLOW_EPHEMERAL_DATA_DIR=1`` is the single documented escape
hatch for harnesses that *deliberately* want throwaway state (e2e runners
exercising the one-shot setup wizard). It is an acknowledgement, not a
default: the guard still verifies writability with it set.
"""

from __future__ import annotations

import contextlib
import logging
import os
from pathlib import Path

logger = logging.getLogger("hive.data_dir")

_PROBE_FILENAME = ".conductor-data-dir-probe"
_ESCAPE_HATCH_ENV = "CONDUCTOR_ALLOW_EPHEMERAL_DATA_DIR"

#: Markers a container runtime drops into the container's own filesystem.
#: Docker creates ``/.dockerenv``; Podman creates ``/run/.containerenv``.
_CONTAINER_MARKERS = ("/.dockerenv", "/run/.containerenv")


class DataDirRefused(RuntimeError):
    """The configured data directory cannot durably hold Conductor state.

    Raised before the vault, state database, or credential store are
    initialized, so a refused startup has written nothing anywhere and the
    process must stop.
    """


def running_in_container() -> bool:
    return any(os.path.exists(marker) for marker in _CONTAINER_MARKERS)


def _ephemerality_acknowledged() -> bool:
    return os.environ.get(_ESCAPE_HATCH_ENV, "").strip().lower() in {"1", "true", "yes"}


def _probe_writable(data_dir: Path) -> None:
    """Prove the directory accepts a create/fsync/delete cycle.

    A real write, not ``os.access``: access(2) reports permission bits, not
    whether this uid can actually write (read-only mounts and some ACL
    layouts pass the bit check and fail the write).
    """
    probe = data_dir / _PROBE_FILENAME
    try:
        with open(probe, "a", encoding="utf-8") as handle:
            handle.write("probe")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise DataDirRefused(
            f"DATA_DIR_UNWRITABLE: {data_dir} is not writable by uid "
            f"{os.getuid()} ({exc}). Refusing to start: state.db, the vault, "
            "and the credential store would fail mid-flight. Fix the volume "
            "mount and its ownership/permissions (see the Conductor README, "
            "'Persistent state')."
        ) from exc
    finally:
        with contextlib.suppress(OSError):
            probe.unlink()


def _probe_mounted(data_dir: Path) -> None:
    """Refuse an in-container data directory that is not a mount point.

    Only called inside a container. A non-mounted path inside the container
    lives in the container's writable layer, which is discarded on recreate —
    so "configured" would be a lie the first time ``docker compose down/up``
    ran. A named volume or bind mount at the path makes it a real mount point.
    """
    if os.path.ismount(data_dir):
        return
    if _ephemerality_acknowledged():
        logger.warning(
            "DATA_DIR_EPHEMERAL_ACKNOWLEDGED: %s is not a mounted filesystem "
            "and WILL BE LOST on container recreate; %s=1 accepted this "
            "deliberately. Never set it where accounts or vault entries must "
            "survive a recreate.",
            data_dir,
            _ESCAPE_HATCH_ENV,
        )
        return
    raise DataDirRefused(
        f"DATA_DIR_EPHEMERAL: {data_dir} is not a mounted filesystem, so "
        "everything written there (accounts, sessions, settings, vault, "
        "credentials) is discarded when this container is recreated. Mount a "
        "volume or host directory at CONDUCTOR_DATA_DIR — see the standalone "
        "docker-compose.yml and the README 'Persistent state' section — or, "
        f"only for throwaway test harnesses, set {_ESCAPE_HATCH_ENV}=1."
    )


def verify_durable_data_dir(data_dir: Path) -> Path:
    """Create, prove writable, and (in containers) prove mounted.

    Returns the resolved directory on success; raises :class:`DataDirRefused`
    otherwise. Call this before any subsystem opens a file under the
    directory, so a refused startup has written nothing.
    """
    resolved = data_dir.expanduser()
    try:
        resolved.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DataDirRefused(
            f"DATA_DIR_UNWRITABLE: cannot create data directory {resolved} "
            f"({exc}). Refusing to start rather than serving state that "
            "cannot be persisted."
        ) from exc
    _probe_writable(resolved)
    if running_in_container():
        _probe_mounted(resolved)
    return resolved
