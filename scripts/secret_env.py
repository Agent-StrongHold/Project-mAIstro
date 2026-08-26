#!/usr/bin/env python3
"""Write `.env` without ever exposing a secret through the file's mode (#357).

The installer used to do this:

    cat > "$ENV_FILE" <<EOF
    MAISTRO_ACCESS_TOKEN=${token}
    ...
    EOF
    chmod 600 "$ENV_FILE"

`cat >` creates the file under the caller's umask -- 0644 on most systems, 0664
under a permissive one -- and every secret is written before `chmod` narrows it.
Any process that can read the directory can read the credentials in that window,
and a crash inside it leaves them world-readable permanently. `append_env_once`
and `get.sh`'s `cp` of a legacy `.env` had the same shape.

So mode comes first, and never after:

* A **new** file is created with `O_CREAT | O_EXCL` at 0600. Exclusive because
  it also settles what happens when something is already there -- the caller
  decides deliberately rather than clobbering.
* An **existing** file is updated by writing a fresh temp file in the same
  directory (same filesystem, so `os.replace` is atomic), fsyncing it, and
  replacing. A reader either sees the whole old file or the whole new one, and
  an interrupted run leaves the old one intact rather than a truncated file
  missing half its keys.
* `umask(0o077)` wraps every write, so even a path that reaches `open()`
  without an explicit mode cannot widen the result.

## Refusing rather than fixing

`validate_target` rejects a symlink, a file owned by someone else, one with
extra hard links, or one already group/other-readable. It does not quietly
`chmod` them: each of those means something other than this installer has a
handle on the path, and narrowing the mode does not take that handle away.
A hard link in particular survives `chmod` -- the other name still refers to
the same inode, and its holder reads whatever we write.

The one exception is a file this installer can prove is already safe: a
0600 file owned by the caller with one link is preserved and updated in place,
because that is the ordinary re-run.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path

#: Owner read/write only. The whole point of the module.
SECRET_MODE = 0o600

#: Mode bits that must never be set on a file holding credentials.
FORBIDDEN_MODE = stat.S_IRWXG | stat.S_IRWXO


class UnsafeEnvFile(Exception):
    """The target cannot be written to safely, and narrowing it would not help."""


@contextmanager
def _restrictive_umask() -> Iterator[None]:
    """Force 0077 for the enclosing block.

    Belt and braces: every open() below already passes an explicit mode, but a
    future edit that forgets one still cannot produce a readable file.
    """
    previous = os.umask(0o077)
    try:
        yield
    finally:
        os.umask(previous)


def validate_target(path: Path) -> bool:
    """Return True if `path` exists and is safe to update; False if absent.

    Raises `UnsafeEnvFile` when it exists but writing to it would leak.
    """
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False

    if stat.S_ISLNK(info.st_mode):
        raise UnsafeEnvFile(
            f"{path} is a symlink. Writing through it would put credentials "
            f"wherever it points, which is not necessarily a place you control."
        )
    if not stat.S_ISREG(info.st_mode):
        raise UnsafeEnvFile(f"{path} is not a regular file.")
    if info.st_nlink > 1:
        raise UnsafeEnvFile(
            f"{path} has {info.st_nlink} hard links. Another name refers to the "
            f"same inode, and chmod would not take that reference away -- "
            f"whoever holds it would read every secret written here."
        )
    if info.st_uid != os.getuid():
        raise UnsafeEnvFile(
            f"{path} is owned by uid {info.st_uid}, not {os.getuid()}. "
            f"Refusing to write credentials into another user's file."
        )
    if info.st_mode & FORBIDDEN_MODE:
        raise UnsafeEnvFile(
            f"{path} is mode {stat.filemode(info.st_mode)} — readable beyond its "
            f"owner. It may already have been exposed; move it aside and re-run "
            f"so a fresh one is created at 0600."
        )
    return True


def _fsync_dir(directory: Path) -> None:
    """Persist the rename itself, not just the bytes it points at.

    Without this the replace can be lost by a crash even though the temp file's
    contents were fsynced.
    """
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    except OSError:
        # Not every filesystem allows fsync on a directory handle. The replace
        # is still atomic; only its durability across a power loss is weaker.
        pass
    finally:
        os.close(fd)


def create_exclusive(path: Path, text: str) -> None:
    """Create `path` at 0600 and write `text`. Fails if anything is there.

    `O_EXCL` is the atomic part: there is no instant at which the file exists
    with a wider mode, and no chance of writing into a file someone else just
    created at the same path.
    """
    with _restrictive_umask():
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, SECRET_MODE)
        try:
            os.write(fd, text.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
    _fsync_dir(path.parent)


def atomic_write(path: Path, text: str) -> None:
    """Replace `path`'s contents with `text`, atomically, at 0600.

    The temp file is created in the same directory so `os.replace` is a rename
    within one filesystem. Written to a different directory it would be a copy,
    which is neither atomic nor guaranteed to keep the mode.
    """
    directory = path.parent
    with _restrictive_umask():
        fd, tmp_name = tempfile.mkstemp(dir=directory, prefix=".env.", suffix=".tmp")
        tmp = Path(tmp_name)
        try:
            os.fchmod(fd, SECRET_MODE)
            os.write(fd, text.encode("utf-8"))
            os.fsync(fd)
            os.close(fd)
            os.replace(tmp, path)
        except BaseException:
            # Roll back: the target keeps whatever it had, and no partial file
            # with secrets in it is left lying around.
            with suppress(OSError):
                os.close(fd)
            tmp.unlink(missing_ok=True)
            raise
    _fsync_dir(directory)


def write(path: Path, text: str) -> None:
    """Create or replace, whichever the target calls for, always at 0600."""
    if validate_target(path):
        atomic_write(path, text)
    else:
        create_exclusive(path, text)


def _lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8").splitlines()


def _rendered(lines: list[str]) -> str:
    return "\n".join(lines) + "\n" if lines else ""


def set_key(path: Path, key: str, value: str, *, only_if_blank: bool = False) -> None:
    """Insert or replace `key`. With `only_if_blank`, a set value is kept."""
    lines = _lines(path)
    prefix = f"{key}="
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            if only_if_blank and line[len(prefix) :].strip() != "":
                return
            lines[index] = prefix + value
            break
    else:
        lines.append(prefix + value)
    write(path, _rendered(lines))


def append_once(path: Path, key: str, value: str) -> None:
    """Add `key` only if it is absent. An existing value is never touched."""
    lines = _lines(path)
    prefix = f"{key}="
    if any(line.startswith(prefix) for line in lines):
        return
    lines.append(prefix + value)
    write(path, _rendered(lines))


def ensure_api_keys(path: Path, token: str) -> None:
    """Make sure the JSON array in `API_KEYS` contains `token`."""
    lines = _lines(path)
    prefix = "API_KEYS="
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            try:
                current = json.loads(line[len(prefix) :]) or []
                if not isinstance(current, list):
                    current = []
            except json.JSONDecodeError:
                current = []
            if token not in current:
                current.append(token)
            lines[index] = prefix + json.dumps(current)
            break
    else:
        lines.append(prefix + json.dumps([token]))
    write(path, _rendered(lines))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write .env safely.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create", help="create at 0600, reading content from stdin")
    p_create.add_argument("path", type=Path)

    p_write = sub.add_parser("write", help="create or replace, reading content from stdin")
    p_write.add_argument("path", type=Path)

    p_set = sub.add_parser("set-key", help="insert or replace one key")
    p_set.add_argument("path", type=Path)
    p_set.add_argument("key")
    p_set.add_argument("value")
    p_set.add_argument("--only-if-blank", action="store_true")

    p_append = sub.add_parser("append-once", help="add a key only if absent")
    p_append.add_argument("path", type=Path)
    p_append.add_argument("key")
    p_append.add_argument("value")

    p_keys = sub.add_parser("ensure-api-keys", help="add a token to the API_KEYS array")
    p_keys.add_argument("path", type=Path)
    p_keys.add_argument("token")

    p_check = sub.add_parser("check", help="validate the target without writing")
    p_check.add_argument("path", type=Path)

    args = parser.parse_args(argv)

    try:
        if args.command == "create":
            create_exclusive(args.path, sys.stdin.read())
        elif args.command == "write":
            write(args.path, sys.stdin.read())
        elif args.command == "set-key":
            set_key(args.path, args.key, args.value, only_if_blank=args.only_if_blank)
        elif args.command == "append-once":
            append_once(args.path, args.key, args.value)
        elif args.command == "ensure-api-keys":
            ensure_api_keys(args.path, args.token)
        elif args.command == "check":
            validate_target(args.path)
    except UnsafeEnvFile as exc:
        # The message names the path and the reason; it never echoes a value.
        print(f"refusing to write secrets: {exc}", file=sys.stderr)
        return 2
    except FileExistsError:
        print(f"refusing to overwrite {args.path}: it already exists", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
