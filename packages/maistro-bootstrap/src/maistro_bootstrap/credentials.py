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
never needs to parse the file in Python, so there is deliberately no reader or
shredder here to drift out of step with it.

Headless installs stage the same file themselves and point
MAISTRO_BOOTSTRAP_CREDENTIALS_FILE at it — same shape, same
consume-once-and-shred semantics.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

from maistro_bootstrap.schema import InstallAnswersV1

BOOTSTRAP_CREDENTIALS_FILENAME = "bootstrap-credentials.json"
ENV_CREDENTIALS_FILE = "MAISTRO_BOOTSTRAP_CREDENTIALS_FILE"

_REQUIRED_KEYS = frozenset({"admin_username", "admin_password", "user_username", "user_password"})


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


def write_bootstrap_credentials(target_dir: Path, creds: dict[str, Any]) -> Path:
    """Write the staged credentials file with owner-only permissions.

    The mode is set before any secret byte lands in the file: create 0600
    first, then write.
    """
    validate_bootstrap_credentials(creds)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / BOOTSTRAP_CREDENTIALS_FILENAME
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(creds, fh, indent=2)
        fh.write("\n")
    if os.name != "nt":
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return path
