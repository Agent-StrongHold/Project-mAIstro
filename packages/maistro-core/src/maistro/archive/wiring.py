"""Selecting an archive backend from configuration (ADR-082226-f436).

Off by default (decision 9): no `archive_url` means no archive store and today's
behaviour exactly, with no warning. A warning on a deliberate absence is how
operators learn to ignore warnings.

What this module does *not* do is decide what gets archived. Eligibility — which
decay weight, which age, which access recency makes a record cold — is open
question 1 of the ADR, deliberately unset because it is a policy question with a
measurable answer and guessing it would freeze a number nobody has data for.
Construction and policy are separable, and this is the half that is decidable
now: a deployment can name where its archive lives before anything writes to it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

from maistro.archive.types import ArchiveError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from maistro.archive.protocols import ArchiveStore

#: URL schemes that name an archive backend.
FILE_SCHEME = "file"
S3_SCHEMES = ("s3", "s3+http", "s3+https")


def build_archive_store(archive_url: str) -> ArchiveStore | None:
    """Build the archive store a URL names, or ``None`` when none is configured.

    ``file:///var/lib/maistro/archive`` selects the local directory backend.

    ``s3://bucket`` selects object storage; ``s3+http://bucket?endpoint=host:9000``
    and ``s3+https://…`` point at an S3-compatible service. The endpoint is part
    of the URL rather than an environment variable because "which bucket, on
    which service" is one decision and splitting it across two places is how a
    deployment ends up writing to the wrong one.

    Credentials are *not* accepted here. They resolve through the vault
    (ADR decision 8, SPEC-011) or boto3's own chain — a URL is configuration,
    configuration gets logged, and a secret in a URL is a secret in the logs.
    """
    url = archive_url.strip()
    if not url:
        return None

    parsed = urlparse(url)
    if parsed.scheme == FILE_SCHEME:
        path = parsed.path
        if not path:
            raise ArchiveError(f"archive_url {url!r} names no directory")
        from maistro.archive.filesystem import FilesystemArchiveStore

        return FilesystemArchiveStore(path)

    if parsed.scheme in S3_SCHEMES:
        bucket = parsed.netloc
        if not bucket:
            raise ArchiveError(f"archive_url {url!r} names no bucket")
        if parsed.username or parsed.password:
            raise ArchiveError(
                "archive_url must not carry credentials; they resolve through the "
                "secret path (SPEC-011) so they do not end up in logs"
            )
        from maistro.archive.s3 import S3ArchiveStore

        return S3ArchiveStore(bucket, endpoint_url=_endpoint(parsed.scheme, parsed.query))

    raise ArchiveError(
        f"archive_url {url!r} names no known backend. Use file:///path, s3://bucket, "
        f"or s3+http(s)://bucket?endpoint=host:port"
    )


def _endpoint(scheme: str, query: str) -> str | None:
    """The S3 endpoint a URL names, or None for AWS proper."""
    if scheme == "s3":
        return None
    endpoint = (parse_qs(query).get("endpoint") or [""])[0].strip()
    if not endpoint:
        raise ArchiveError(f"{scheme}:// requires an ?endpoint=host:port")
    transport = "http" if scheme == "s3+http" else "https"
    if endpoint.startswith(("http://", "https://")):
        return endpoint
    return f"{transport}://{endpoint}"


__all__ = ["FILE_SCHEME", "S3_SCHEMES", "build_archive_store"]
