"""Backends for the archive conformance suite (ADR-082226-f436).

The S3 backend runs against a real S3-compatible **server** over HTTP, not a
patched boto3 client. That distinction is the whole lesson of #122: mocking the
client proves the request was composed and nothing about whether the service
accepts it, and every one of the six PostgreSQL defects found there was invisible
to exactly that style of test.

Two servers are honoured, in order of fidelity:

- `MAISTRO_TEST_S3_ENDPOINT` — a MinIO (or any S3-compatible) endpoint. CI runs
  one, and it is the closest thing to production available offline.
- an in-process `moto` server, started automatically when the extra is installed.
  Lower fidelity than MinIO, but still a real HTTP S3 implementation rather than
  a stub of our own code, so it keeps the suite meaningful on a laptop.

With neither, the S3 parametrisation skips and the filesystem backend still runs.

A skip is not a pass, though, so `MAISTRO_REQUIRE_S3_LEGS` turns the fallbacks
off: with it set, an unreachable `MAISTRO_TEST_S3_ENDPOINT` fails rather than
quietly dropping to moto or to a skip. `quality.yml`'s MinIO coverage job sets
it, because there a missing endpoint means the service failed to start — and a
green job over an unrun leg reports the absence of the gap rather than its
closure, which is the same reason this leg runs against a real server at all.
"""

from __future__ import annotations

import os
import socket
from collections.abc import Iterator
from typing import Any

import pytest

BUCKET = "maistro-archive-test"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="session")
def s3_endpoint() -> Iterator[str | None]:
    """A live S3-compatible endpoint, or None when neither is available."""
    configured = os.getenv("MAISTRO_TEST_S3_ENDPOINT", "").strip()
    if configured:
        yield configured
        return

    if os.getenv("MAISTRO_REQUIRE_S3_LEGS"):
        raise RuntimeError(
            "MAISTRO_REQUIRE_S3_LEGS is set but MAISTRO_TEST_S3_ENDPOINT is empty: "
            "the S3 leg must run against the configured server, not moto and not a skip"
        )

    try:
        from moto.server import ThreadedMotoServer
    except ImportError:
        yield None
        return

    port = _free_port()
    server = ThreadedMotoServer(port=port, verbose=False)
    server.start()
    # Silence any ambient AWS configuration: a developer with real credentials
    # exported must not have this suite reach for their account.
    previous = {
        name: os.environ.get(name)
        for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")
    }
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ.pop("AWS_SESSION_TOKEN", None)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.stop()
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


@pytest.fixture
def s3_bucket(s3_endpoint: str | None) -> Any:
    """An empty bucket on the live endpoint, or a skip."""
    if s3_endpoint is None:
        if os.getenv("MAISTRO_REQUIRE_S3_LEGS"):
            raise RuntimeError(
                "MAISTRO_REQUIRE_S3_LEGS is set but no S3 endpoint resolved: "
                "the S3 leg must not be silently skipped"
            )
        pytest.skip("no S3-compatible endpoint: install moto or set MAISTRO_TEST_S3_ENDPOINT")
    boto3 = pytest.importorskip("boto3")

    client = boto3.client(
        "s3",
        endpoint_url=s3_endpoint,
        region_name="us-east-1",
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID", "testing"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY", "testing"),
    )
    _reset_bucket(client)
    return client


def _reset_bucket(client: Any) -> None:
    """Make the bucket exist and be empty, whichever it currently is."""
    try:
        client.create_bucket(Bucket=BUCKET)
    except Exception as exc:  # already there
        if "BucketAlreadyOwnedByYou" not in str(exc) and "BucketAlreadyExists" not in str(exc):
            raise
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET):
        contents = page.get("Contents") or []
        if contents:
            client.delete_objects(
                Bucket=BUCKET,
                Delete={"Objects": [{"Key": item["Key"]} for item in contents]},
            )


__all__ = ["BUCKET", "s3_bucket", "s3_endpoint"]
