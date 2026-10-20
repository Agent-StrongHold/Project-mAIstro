"""Opt-in local development bootstrap for Turing's service identity.

Turing ships no built-in service key (#858): activating the backend requires an
explicitly provisioned one. This command exists so local development has a safe
way to obtain a unique key — generation, printing, and optional storage —
instead of reaching for a shared constant:

    cd packages/maistro-turing
    python -m backend.provision                          # generate + print
    python -m backend.provision --env-file .env.turing   # also store (0600)

Every invocation generates a fresh 256-bit key via the core secure-random
helper. Nothing is persisted unless ``--env-file`` is given; an existing
TURING_SERVICE_KEY line is never overwritten without ``--force`` (rotation).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from maistro.security.secure_random import secure_urlsafe

KEY_ENV_NAME = "TURING_SERVICE_KEY"
KEY_PREFIX = "sk-svc-turing-"


def generate_service_key() -> str:
    """A fresh, unique service key — never a shared or derived value."""
    return KEY_PREFIX + secure_urlsafe(32)


def store_key_env_line(path: Path, value: str, *, force: bool) -> None:
    """Add (or, with force, rotate) the KEY_ENV_NAME line in a dotenv file.

    The file is written with owner-only permissions; an existing
    TURING_SERVICE_KEY entry is replaced only when ``force`` is set, so a
    casual re-run cannot silently rotate a live credential.
    """
    entries: list[str] = []
    if path.exists():
        entries = path.read_text(encoding="utf-8").splitlines()
    replaced = False
    for index, line in enumerate(entries):
        if line.split("=", 1)[0].strip() == KEY_ENV_NAME:
            if not force:
                raise SystemExit(
                    f"{path}: {KEY_ENV_NAME} is already set; pass --force to rotate it"
                )
            entries[index] = f"{KEY_ENV_NAME}={value}"
            replaced = True
            break
    if not replaced:
        while entries and not entries[-1]:
            entries.pop()
        entries.append(f"{KEY_ENV_NAME}={value}")
    payload = "\n".join(entries) + "\n"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.chmod(path, 0o600)
    except OSError as exc:
        print(f"cannot write {path}: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m backend.provision",
        description=(
            "Generate a unique Turing service identity key "
            "(there is no built-in or default service key)."
        ),
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        metavar="PATH",
        help=f"also store the key as {KEY_ENV_NAME} in this dotenv file (mode 0600)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help=f"with --env-file: replace an existing {KEY_ENV_NAME} (rotation)",
    )
    args = parser.parse_args(argv)
    key = generate_service_key()
    if args.env_file is not None:
        store_key_env_line(args.env_file, key, force=args.force)
        print(
            f"stored {KEY_ENV_NAME} in {args.env_file} (mode 0600); "
            "restart the backend with this file to load it",
            file=sys.stderr,
        )
    else:
        print(
            f"export {KEY_ENV_NAME}=<value below>; "
            "or re-run with --env-file PATH to store it (mode 0600)",
            file=sys.stderr,
        )
    print(key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
