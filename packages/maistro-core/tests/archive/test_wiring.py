"""Configuration selects an archive backend, or none (ADR-082226-f436).

Off by default is a decision, not an oversight: no `archive_url` means today's
system exactly. Everything else here is about the two ways a URL can be wrong
in a way that matters — naming a backend that does not exist, and carrying a
secret into somewhere that gets logged.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from maistro.archive import ArchiveError, FilesystemArchiveStore
from maistro.archive.wiring import build_archive_store


@pytest.mark.parametrize("configured", ["", "   ", "\n"])
def test_no_url_means_no_archive_tier(configured: str) -> None:
    assert build_archive_store(configured) is None


def test_a_file_url_selects_the_directory_backend(tmp_path: Path) -> None:
    store = build_archive_store(f"file://{tmp_path}")

    assert isinstance(store, FilesystemArchiveStore)


async def test_the_directory_backend_writes_where_the_url_says(tmp_path: Path) -> None:
    store = build_archive_store(f"file://{tmp_path}/archive")
    assert store is not None

    key = await store.put(b"payload", scope="learnings")

    assert (tmp_path / "archive" / "learnings" / key.digest).is_file()


def test_a_file_url_with_no_path_is_refused() -> None:
    with pytest.raises(ArchiveError, match="names no directory"):
        build_archive_store("file://")


def test_an_s3_url_selects_object_storage() -> None:
    pytest.importorskip("boto3")

    store = build_archive_store("s3://my-bucket")

    assert type(store).__name__ == "S3ArchiveStore"


def test_an_s3_url_with_no_bucket_is_refused() -> None:
    with pytest.raises(ArchiveError, match="names no bucket"):
        build_archive_store("s3://")


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("s3+http://bucket?endpoint=127.0.0.1:9000", "http://127.0.0.1:9000"),
        ("s3+https://bucket?endpoint=minio.example", "https://minio.example"),
        # An endpoint that already names its transport wins over the scheme's.
        ("s3+http://bucket?endpoint=https://minio.example", "https://minio.example"),
    ],
)
def test_a_compatible_service_endpoint_is_carried_through(url: str, expected: str) -> None:
    """S3-compatible is the point: MinIO, R2 and B2 are named the same way as
    AWS, so the homelab does not need a cloud account to have an archive."""
    pytest.importorskip("boto3")
    from maistro.archive.wiring import _endpoint

    scheme, _, rest = url.partition("://")
    query = rest.partition("?")[2]

    assert _endpoint(scheme, query) == expected


def test_a_compatible_scheme_without_an_endpoint_is_refused() -> None:
    with pytest.raises(ArchiveError, match=r"requires an \?endpoint"):
        build_archive_store("s3+http://bucket")


def test_plain_s3_means_aws_and_needs_no_endpoint() -> None:
    from maistro.archive.wiring import _endpoint

    assert _endpoint("s3", "") is None


@pytest.mark.parametrize(
    "url",
    ["s3://key:secret@bucket", "s3+https://key:secret@bucket?endpoint=minio.example"],
)
def test_credentials_in_the_url_are_refused(url: str) -> None:
    """A URL is configuration, configuration gets logged, and a secret in a URL
    is a secret in the logs. They resolve through the vault instead (SPEC-011)."""
    with pytest.raises(ArchiveError, match="must not carry credentials"):
        build_archive_store(url)


@pytest.mark.parametrize(
    "url", ["gs://bucket", "azure://container", "http://example", "/just/a/path", "bucket"]
)
def test_an_unknown_backend_is_refused_and_says_what_works(url: str) -> None:
    with pytest.raises(ArchiveError, match=re.escape("file:///path")):
        build_archive_store(url)


async def test_the_container_wires_it_from_config(tmp_path: Path) -> None:
    from maistro.container import create_container
    from maistro.types.config import AgentConfig

    container = await create_container(
        AgentConfig(router_api_key="k", archive_url=f"file://{tmp_path}/archive")
    )

    assert isinstance(container.archive_store, FilesystemArchiveStore)


async def test_the_container_defaults_to_no_archive() -> None:
    from maistro.container import create_container
    from maistro.types.config import AgentConfig

    container = await create_container(AgentConfig(router_api_key="k"))

    assert container.archive_store is None


# ── URLs are configuration, and configuration gets logged ─────────


#: A sentinel no message could contain as prose. "secret" collides with the
#: rejection message's own wording ("the secret path (SPEC-011)"), which would
#: make this test fail for a reason that is not a leak.
#:
#: Split across two literals per the convention in `.gitleaks.toml`: a
#: credential-shaped value on one line is what `generic-api-key` matches, and
#: the repo fixes that by concatenation rather than by allowlisting code.
_SECRET = "hunter2" + "-Zx9Q"


@pytest.mark.parametrize(
    "url",
    [
        f"s3://key:{_SECRET}@bucket",
        f"gs://key:{_SECRET}@bucket",
        f"file://key:{_SECRET}@/path",
        f"s3+https://key:{_SECRET}@bucket?endpoint=minio",
        f"s3://{_SECRET}@bucket",
    ],
)
def test_no_error_echoes_credentials(url: str) -> None:
    """These raise at startup, uncaught, into process logs — the same reason
    the database-config check redacts."""
    with pytest.raises(ArchiveError) as excinfo:
        build_archive_store(url)

    assert _SECRET not in str(excinfo.value)


def test_a_rejected_url_stays_diagnosable() -> None:
    with pytest.raises(ArchiveError) as excinfo:
        build_archive_store("gs://my-bucket")

    message = str(excinfo.value)
    assert "gs" in message
    assert "my-bucket" in message


def test_the_bucket_is_the_host_not_the_netloc() -> None:
    """`netloc` carries userinfo and any port, so a bucket read from it would
    be `user:pw@bucket` or `bucket:9000`."""
    pytest.importorskip("boto3")

    store = build_archive_store("s3://my-bucket")

    assert store._bucket == "my-bucket"  # type: ignore[union-attr]


def test_bucket_names_are_case_insensitive() -> None:
    """S3 bucket names are lowercase by rule, so two spellings addressing one
    bucket is the right behaviour rather than a surprise."""
    pytest.importorskip("boto3")

    store = build_archive_store("s3://My-Bucket")

    assert store._bucket == "my-bucket"  # type: ignore[union-attr]


def test_a_port_on_the_bucket_is_refused() -> None:
    """Dropping it silently would leave an operator believing they configured
    an endpoint when they configured nothing."""
    with pytest.raises(ArchiveError, match="port belongs"):
        build_archive_store("s3://bucket:9000")
