"""The archive tier: cold, durable, still authoritative (ADR-082226-f436).

Below `Long-term` in ADR-082226-5104's memory hierarchy. An archived record has
*moved*, not been backed up and not been deleted — it is the same authoritative
record in storage priced for reading it rarely.

`S3ArchiveStore` is re-exported lazily so that importing this package does not
import boto3. The S3 backend is behind the `[s3]` extra (ADR decision 4), and
`maistro-core` must import cleanly without it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from maistro.archive.filesystem import FilesystemArchiveStore
from maistro.archive.protocols import ArchiveStore
from maistro.archive.types import (
    ArchivedRecordNotFound,
    ArchiveError,
    ArchiveIntegrityError,
    ArchiveKey,
    InvalidArchiveScope,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from maistro.archive.s3 import S3ArchiveStore

__all__ = [
    "ArchiveError",
    "ArchiveIntegrityError",
    "ArchiveKey",
    "ArchiveStore",
    "ArchivedRecordNotFound",
    "FilesystemArchiveStore",
    "InvalidArchiveScope",
    "S3ArchiveStore",
]


def __getattr__(name: str) -> Any:
    """Import the S3 backend only when it is asked for."""
    if name == "S3ArchiveStore":
        from maistro.archive.s3 import S3ArchiveStore

        return S3ArchiveStore
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
