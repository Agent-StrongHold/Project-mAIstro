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
from urllib.parse import ParseResult, parse_qs, urlparse, urlunparse

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

    # Credentials are checked before anything else, and never echoed. Every
    # error below reports a redacted URL for the same reason the database-config
    # check does: these raise at startup, uncaught, into process logs.
    if parsed.username or parsed.password:
        raise ArchiveError(
            "archive_url must not carry credentials; they resolve through the "
            "secret path (SPEC-011) so they do not end up in logs"
        )
    safe = _redact(parsed)

    if parsed.scheme == FILE_SCHEME:
        path = parsed.path
        if not path:
            raise ArchiveError(f"archive_url {safe!r} names no directory")
        from maistro.archive.filesystem import FilesystemArchiveStore

        return FilesystemArchiveStore(path)

    if parsed.scheme in S3_SCHEMES:
        # `hostname`, not `netloc`: netloc carries userinfo and any port, so a
        # bucket read from it would be "bucket:9000" or "user:pw@bucket". The
        # lowercasing hostname applies is correct here — S3 bucket names are
        # lowercase by rule, so two spellings addressing one bucket is right.
        bucket = parsed.hostname or ""
        if not bucket:
            raise ArchiveError(f"archive_url {safe!r} names no bucket")
        if parsed.port is not None:
            raise ArchiveError(
                f"archive_url {safe!r} puts a port on the bucket. The port belongs "
                f"to the service: s3+http(s)://bucket?endpoint=host:port"
            )
        from maistro.archive.s3 import S3ArchiveStore

        return S3ArchiveStore(bucket, endpoint_url=_endpoint(parsed.scheme, parsed.query))

    raise ArchiveError(
        f"archive_url {safe!r} names no known backend. Use file:///path, s3://bucket, "
        f"or s3+http(s)://bucket?endpoint=host:port"
    )


def _redact(parsed: ParseResult) -> str:
    """The URL without userinfo, for an error that will be logged."""
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    userinfo = "***:***@" if (parsed.username or parsed.password) else ""
    return urlunparse((parsed.scheme, f"{userinfo}{host}", parsed.path, "", parsed.query, ""))


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
