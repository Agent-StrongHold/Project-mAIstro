"""Archive-tier implementations (ADR-082226-d3dd).

`FilesystemArchiveStore` is imported eagerly — it has no third-party dependency
and is what the homelab deployment uses.

`S3ArchiveStore` is **not** imported here. It needs `aioboto3`, which lives
behind the `maistro-core[s3]` extra, and importing it at package import time
would make `from maistro.memory.archive import FilesystemArchiveStore` fail on
every install without the extra — which is the default install. Reach it through
`s3_archive_store()`, which imports lazily and raises a message naming the extra
rather than an ImportError naming a module the reader has never heard of.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from maistro.memory.archive.filesystem import FilesystemArchiveStore

if TYPE_CHECKING:
    from maistro.memory.archive.s3 import S3ArchiveStore

__all__ = ["FilesystemArchiveStore", "s3_archive_store"]


def s3_archive_store(**kwargs: Any) -> S3ArchiveStore:
    """Construct an `S3ArchiveStore`, importing its SDK only when asked.

    ADR-082226-d3dd §6: a deployment that does not archive must not pay for a
    cloud SDK, and `maistro-core` must import cleanly with the extra absent.
    """
    try:
        from maistro.memory.archive.s3 import S3ArchiveStore
    except ImportError as exc:  # pragma: no cover - exercised by a test that hides the module
        msg = (
            "S3ArchiveStore needs the optional S3 dependencies. "
            "Install them with: pip install 'maistro-core[s3]'"
        )
        raise ImportError(msg) from exc
    return S3ArchiveStore(**kwargs)
