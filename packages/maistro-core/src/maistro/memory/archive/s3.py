"""S3-compatible archive store (ADR-082226-d3dd §7).

**S3-compatible, not AWS.** `endpoint_url` is configurable, so MinIO,
Cloudflare R2, Backblaze B2 and anything else speaking the protocol work. The
tests exercise this against a real MinIO rather than a mocked client — a mocked
object store proves the call was made with the arguments the test already knew,
which is not the property worth checking about a storage backend.

This module is behind the `maistro-core[s3]` extra and is imported lazily via
`maistro.memory.archive.s3_archive_store`. Importing it here at package level
would break `maistro-core`'s base install, which is the case §6 forbids.

Credentials come from the secret path (SPEC-011). This class takes already-
resolved values and never reads config or a database itself: a storage backend
that knows how to find its own secrets is a storage backend that can be made to
find someone else's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import aioboto3
from botocore.exceptions import ClientError

from maistro.protocols.archive import (
    ArchivedRecord,
    ArchiveKeyNotFoundError,
    content_digest,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

#: S3 error codes that mean "no such object", as opposed to a real failure.
#: `404` appears because `head_object` reports it that way while `get_object`
#: uses `NoSuchKey` — the same condition, two spellings, and treating either as
#: an error would make a missing object look like an outage.
_MISSING_CODES = frozenset({"NoSuchKey", "404", "NoSuchBucket"})


class S3ArchiveStore:
    """`ArchiveStore` over any S3-compatible object store."""

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None = None,
        region_name: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        prefix: str = "",
    ) -> None:
        self._bucket = bucket
        self._prefix = prefix.strip("/")
        self._session = aioboto3.Session()
        self._client_kwargs: dict[str, Any] = {"service_name": "s3"}
        if endpoint_url:
            self._client_kwargs["endpoint_url"] = endpoint_url
        if region_name:
            self._client_kwargs["region_name"] = region_name
        if access_key_id and secret_access_key:
            self._client_kwargs["aws_access_key_id"] = access_key_id
            self._client_kwargs["aws_secret_access_key"] = secret_access_key

    def _object_key(self, key: str) -> str:
        return f"{self._prefix}/{key}" if self._prefix else key

    def _strip_prefix(self, object_key: str) -> str:
        return object_key[len(self._prefix) + 1 :] if self._prefix else object_key

    async def put(self, key: str, payload: bytes) -> str:
        digest = content_digest(payload)
        async with self._session.client(**self._client_kwargs) as s3:
            # Idempotent by digest rather than by overwrite. S3 PUT is already
            # idempotent in effect, but re-uploading a 50MB object on every
            # retry of an interrupted sweep is a real cost, and a HEAD is one
            # round trip against a body transfer.
            try:
                head = await s3.head_object(Bucket=self._bucket, Key=self._object_key(key))
                if head.get("Metadata", {}).get("digest") == digest:
                    return digest
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") not in _MISSING_CODES:
                    raise
            await s3.put_object(
                Bucket=self._bucket,
                Key=self._object_key(key),
                Body=payload,
                # Stored so `put` can be idempotent without downloading, and so
                # the object carries its own address independently of the stub
                # row — a bucket restored from a snapshot is still verifiable.
                Metadata={"digest": digest},
            )
        return digest

    async def get(self, key: str) -> ArchivedRecord:
        async with self._session.client(**self._client_kwargs) as s3:
            try:
                response = await s3.get_object(Bucket=self._bucket, Key=self._object_key(key))
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") in _MISSING_CODES:
                    raise ArchiveKeyNotFoundError(key) from exc
                raise
            payload = await response["Body"].read()
            # The stored digest is what was written; recomputing and comparing
            # is what catches a truncated or corrupted transfer. Falling back to
            # the computed digest when metadata is absent means an object
            # uploaded by some other tool still reads, it simply cannot be
            # cross-checked.
            stored = response.get("Metadata", {}).get("digest") or content_digest(payload)
        record = ArchivedRecord(key=key, payload=payload, digest=stored)
        record.verify()
        return record

    async def exists(self, key: str) -> bool:
        async with self._session.client(**self._client_kwargs) as s3:
            try:
                await s3.head_object(Bucket=self._bucket, Key=self._object_key(key))
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") in _MISSING_CODES:
                    return False
                raise
            return True

    async def list_keys(self, prefix: str = "") -> AsyncIterator[str]:
        async with self._session.client(**self._client_kwargs) as s3:
            paginator = s3.get_paginator("list_objects_v2")
            # Paginated rather than a single list_objects_v2 call, which caps at
            # 1000 keys and reports no error when it truncates. An archive is
            # the one tier expected to exceed that.
            async for page in paginator.paginate(
                Bucket=self._bucket, Prefix=self._object_key(prefix) if prefix else self._prefix
            ):
                for obj in page.get("Contents", []):
                    yield self._strip_prefix(obj["Key"])

    async def delete(self, key: str) -> bool:
        existed = await self.exists(key)
        async with self._session.client(**self._client_kwargs) as s3:
            # S3 DELETE is unconditionally successful, so the HEAD above is what
            # makes the "was it there" answer real rather than always True.
            await s3.delete_object(Bucket=self._bucket, Key=self._object_key(key))
        return existed

    async def ensure_bucket(self) -> None:
        """Create the bucket if absent. For tests and first-run setup."""
        async with self._session.client(**self._client_kwargs) as s3:
            try:
                await s3.head_bucket(Bucket=self._bucket)
            except ClientError:
                await s3.create_bucket(Bucket=self._bucket)
