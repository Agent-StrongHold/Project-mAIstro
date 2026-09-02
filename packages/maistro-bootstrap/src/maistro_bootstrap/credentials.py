"""Bootstrap credentials staging — the one secret-bearing install artifact.

The answers schema is deliberately secret-free (SPEC-180). First-run account
credentials collected by the wizard travel through exactly one file:
`bootstrap-credentials.json`, written 0600 next to the other materialized
artifacts, consumed once by the installer's bootstrap step (POST
/v1/setup/complete) and then shredded (SPEC-072726-3439 Phases 1/3).

This module owns only the *staging* half. Consumption and shredding live in
`install.sh` (`bootstrap_first_run` / `shred_file`), which posts the file
straight to the API with `curl --data-binary` and shreds it on every terminal
path — success, 409-already-provisioned, and setup-already-complete alike. It
never needs to parse the file in Python, so there is deliberately no
consumer-side reader here to drift out of step with it. The one bounded reader
this module does have (`staged_credentials_valid`) never consumes secrets: it
only decides whether an already-staged file is trustworthy enough to reuse
instead of re-staging (#809).

Headless installs stage the same file themselves and point
MAISTRO_BOOTSTRAP_CREDENTIALS_FILE at it — same shape, same
consume-once-and-shred semantics.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any

from maistro_bootstrap.schema import InstallAnswersV1

BOOTSTRAP_CREDENTIALS_FILENAME = "bootstrap-credentials.json"
ENV_CREDENTIALS_FILE = "MAISTRO_BOOTSTRAP_CREDENTIALS_FILE"

_OWNER_ONLY = stat.S_IRUSR | stat.S_IWUSR

_REQUIRED_KEYS = frozenset({"admin_username", "admin_password", "user_username", "user_password"})


class UnsafeStagedCredentialsError(RuntimeError):
    """The staged-credentials path is held by something we refuse to write through.

    Raised rather than quietly worked around: a trailing chmod would repair the
    symptom (the mode) while leaving whatever holds the path — a planted
    symlink, a device node — exactly where it was (#809).
    """


def build_bootstrap_credentials(
    answers: InstallAnswersV1,
    *,
    admin_password: str,
    user_password: str,
    hardware_preset: str = "auto",
) -> dict[str, Any]:
    """Assemble the /v1/setup/complete payload from answers + collected secrets."""
    modules: list[str] = []
    if answers.crypto_profile != "no_crypto":
        modules.append("crypto_identity")
    return {
        "admin_username": answers.admin_user,
        "admin_password": admin_password,
        "user_username": answers.daily_driver_user,
        "user_password": user_password,
        "optional_modules": modules,
        "hardware_preset": hardware_preset,
    }


def validate_bootstrap_credentials(data: dict[str, Any]) -> dict[str, Any]:
    missing = sorted(_REQUIRED_KEYS - data.keys())
    if missing:
        raise ValueError(f"bootstrap credentials missing keys: {', '.join(missing)}")
    for key in _REQUIRED_KEYS:
        if not isinstance(data[key], str) or not data[key]:
            raise ValueError(f"bootstrap credentials key {key!r} must be a non-empty string")
    return data


def _fsync_dir(directory: Path) -> None:
    """Persist the rename itself, not just the bytes it points at (best effort)."""
    try:
        fd = os.open(str(directory), os.O_RDONLY)
    except OSError:  # pragma: no cover — platforms without directory fds
        return
    try:
        os.fsync(fd)
    except OSError:  # pragma: no cover — some filesystems reject dir fsync
        pass
    finally:
        os.close(fd)


def staged_credentials_valid(path: Path) -> bool:
    """True iff `path` holds a privately-owned, parse-valid staging of credentials.

    Existence alone is not success (#809 AC-3): a truncated file left by an
    interrupted run parses as nothing, so it is not "already staged" — it is
    wreckage to be re-staged over, never input to trust.

    Refuses (raises) when the path is held by a symlink or anything other than
    a regular file rather than returning False: a symlink is not a stale file
    to overwrite but a redirect, and on POSIX `st_nlink > 1` means another name
    reads whatever lands here regardless of mode. Narrowing either with chmod
    would hide the cause, so both are surfaced as errors instead.
    """
    if not os.path.lexists(path):
        return False
    if path.is_symlink():
        raise UnsafeStagedCredentialsError(
            f"refusing to use {path}: it is a symlink, and credentials must never be staged through one"
        )
    if not path.is_file():
        raise UnsafeStagedCredentialsError(
            f"refusing to use {path}: not a regular file, so credentials cannot be staged there"
        )
    try:
        info = path.stat()
        payload = json.loads(path.read_text(encoding="utf-8"))
        validate_bootstrap_credentials(payload)
    except (OSError, UnicodeDecodeError, ValueError):
        # Unreadable, not JSON, or structurally wrong (missing/empty secrets):
        # wreckage, not staged input.
        return False
    if not stat.S_ISREG(info.st_mode):
        return False
    if os.name != "nt":
        if stat.S_IMODE(info.st_mode) != _OWNER_ONLY:
            return False
        if info.st_nlink != 1:
            return False
    return True


def _stage_credentials_atomically(path: Path, creds: dict[str, Any]) -> None:
    """Write `creds` to a fresh private temp file, then promote it with `os.replace`.

    The temp file is created in the same directory so the promotion is a
    rename within one filesystem — a reader sees either the whole previous
    file or the whole new one, never a truncated mix (#809 AC-2).

    `tempfile.mkstemp` opens `O_CREAT | O_EXCL` on an unguessable name, so the
    new inode cannot be pre-planted by a symlink or collide with an existing
    one, and it is created 0600 — secret bytes never touch a pre-existing
    inode, so a leftover permissive file's mode never applies to them
    (#809 AC-1). The explicit `fchmod` pins the mode regardless of umask.
    `os.replace` is a rename: it never follows a link at the destination, so
    even a symlink planted in the race after the pre-check cannot redirect
    the bytes.
    """
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        if os.name != "nt":
            os.fchmod(fd, _OWNER_ONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(creds, fh, indent=2)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        # Roll back: the target keeps whatever it had, and no partial file
        # with secrets in it is left lying around.
        with suppress(OSError):
            os.close(fd)
        tmp.unlink(missing_ok=True)
        raise
    _fsync_dir(path.parent)


def write_bootstrap_credentials(target_dir: Path, creds: dict[str, Any]) -> Path:
    """Stage the credentials file privately, atomically, never through a link.

    - New secrets land in a fresh 0600 inode promoted by `os.replace`; no
      secret byte is ever written into a pre-existing file, permissive or not.
    - A pre-existing file is reused only when `staged_credentials_valid`
      accepts it — parse-valid JSON, owner-only, unshared — because the file
      is consume-once state and an already-good staging wins over a re-prompt
      (the CLI's "already staged" skip relies on the same check). Anything
      else that is there is atomically replaced, not trusted.
    - A symlink at the final path is refused outright: the write fails rather
      than following the link or silently unlinking the attacker's redirect.
    """
    validate_bootstrap_credentials(creds)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / BOOTSTRAP_CREDENTIALS_FILENAME
    if staged_credentials_valid(path):
        return path
    _stage_credentials_atomically(path, creds)
    return path
