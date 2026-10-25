"""Workspace mount management for sandbox containers."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import structlog

logger = structlog.get_logger()

# Base directory for workspaces inside containers
CONTAINER_WORKSPACE = "/workspace"

# Allowed host paths that can be mounted into containers.
# Include `/private/tmp/...` because macOS resolves `/tmp` → `/private/tmp`.
# Also include the platform temp dir's own `maistro-workspace` (usually the
# same as the hardcoded `/tmp` entry, but not when `$TMPDIR` points elsewhere,
# e.g. `/var/tmp` or a CI-specific dir) — callers that build their default
# workspace root from `tempfile.gettempdir()` (maistro_rsi.runner) must not
# fail validation for honoring the platform's own temp directory.
ALLOWED_HOST_ROOTS = (
    Path("/tmp/maistro-workspace"),  # nosec B108 — security allowlist, not a write target
    Path("/private/tmp/maistro-workspace"),  # nosec B108 — macOS symlink target of /tmp
    Path(tempfile.gettempdir()) / "maistro-workspace",  # nosec B108 — see comment above
    Path("/repos"),
)


def validate_workspace_path(path: str) -> Path:
    """Validate and resolve a workspace path.

    Ensures the path is within allowed prefixes to prevent
    arbitrary filesystem access via container mounts.
    """
    allowed_roots = tuple(root.resolve() for root in ALLOWED_HOST_ROOTS)
    # The normalized-string check is the containment a scanner can follow;
    # the resolved check below is the one that closes the symlink escape.
    normalized = os.path.normpath(path)
    if not any(
        normalized == str(root) or normalized.startswith(str(root) + os.sep)
        for root in (*allowed_roots, *ALLOWED_HOST_ROOTS)
    ):
        allowed = tuple(str(root) for root in allowed_roots)
        raise ValueError(
            f"Workspace path {path} is not in an allowed location. Allowed roots: {allowed}"
        )
    resolved = Path(normalized).resolve()

    Containment uses ``os.path.realpath`` + ``startswith(root + sep)`` — the
    guard CodeQL's ``py/path-injection`` models — rather than
    ``Path.resolve()`` / ``is_relative_to``, which the scanner does not treat
    as a sanitizer even when the check is correct.
    """
    allowed_roots = tuple(os.path.realpath(str(root)) for root in ALLOWED_HOST_ROOTS)
    # Lexical prefilter against both realpath'd and configured spellings so a
    # macOS ``/tmp`` request still matches before realpath rewrites it to
    # ``/private/tmp``.
    lexical_roots = (*allowed_roots, *(str(root) for root in ALLOWED_HOST_ROOTS))
    normalized = os.path.normpath(path)
    if not any(
        normalized == root or normalized.startswith(root + os.sep) for root in lexical_roots
    ):
        raise ValueError(
            f"Workspace path {path} is not in an allowed location. Allowed roots: {allowed_roots}"
        )

    resolved_str = os.path.realpath(normalized)
    # Sink uses sit inside the matching branch so the startswith guard
    # dominates them for the path-injection query.
    for root_str in allowed_roots:
        if resolved_str == root_str or resolved_str.startswith(root_str + os.sep):
            return Path(resolved_str)

    raise ValueError(
        f"Workspace path {path} is not in an allowed location. Allowed roots: {allowed_roots}"
    )


def ensure_workspace(path: str) -> Path:
    """Validate workspace path and create directory if needed."""
    resolved = validate_workspace_path(path)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved
