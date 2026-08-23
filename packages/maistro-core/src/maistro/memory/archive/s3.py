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

from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, Any, cast

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
#:
#: `NoSuchBucket` is deliberately **not** here. A wrong bucket name or a deleted
#: bucket is a store-level failure, and folding it in made `get` raise
#: `ArchiveKeyNotFoundError` and `exists` return `False` — the archive
#: cheerfully reporting that a record is not there because it could not look.
#: That is precisely what this protocol forbids: "it must never answer 'nothing
#: here' in a way a caller could mistake for 'no such record'". It stays a
#: `ClientError` so an outage is distinguishable from data inconsistency.
_MISSING_CODES = frozenset({"NoSuchKey", "404"})


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
        if bool(access_key_id) != bool(secret_access_key):
            # Half a credential silently became *no* credential, and boto then
            # fell back to whatever the host offered — an instance role, a
            # developer's `~/.aws` profile. On a machine with either, a
            # malformed secret configuration does not fail; it archives into
            # somebody else's account. This module's whole premise is that it
            # takes already-resolved values and never goes looking (SPEC-011),
            # so an incomplete pair is a configuration error, not a hint.
            missing = "secret_access_key" if access_key_id else "access_key_id"
            msg = (
                f"S3ArchiveStore was given one half of an explicit credential pair; "
                f"{missing} is missing. Supply both, or neither to use the ambient "
                f"credential chain deliberately."
            )
            raise ValueError(msg)
        if access_key_id and secret_access_key:
            self._client_kwargs["aws_access_key_id"] = access_key_id
            self._client_kwargs["aws_secret_access_key"] = secret_access_key

    def _client(self) -> AbstractAsyncContextManager[Any]:
        """One typed seam over the SDK's untyped client factory.

        `aioboto3` ships no `py.typed` marker, so `Session.client(...)` is
        opaque and every `async with` over it is an error pyright cannot check —
        twelve of them across six call sites. Casting once, here, is honest
        about exactly where the type information stops, and leaves the call
        sites readable. Scattering twelve `# pyright: ignore` comments would
        record the same fact twelve times and suppress any *real* context-manager
        mistake at those lines along with it.
        """
        return cast(AbstractAsyncContextManager[Any], self._session.client(**self._client_kwargs))

    def _object_key(self, key: str) -> str:
        return f"{self._prefix}/{key}" if self._prefix else key

    def _strip_prefix(self, object_key: str) -> str:
        return object_key[len(self._prefix) + 1 :] if self._prefix else object_key

    async def put(self, key: str, payload: bytes) -> str:
        digest = content_digest(payload)
        async with self._client() as s3:
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

    async def get(self, key: str, *, expected_digest: str | None = None) -> ArchivedRecord:
        """Read one archived payload, digest-verified.

        Two attestations, in order of authority: `expected_digest` from the
        caller's stub row, then the digest `put` stored in object metadata. The
        metadata one is a real cross-check — it was written before the transfer
        this call is verifying — but it lives in the same object as the payload,
        so a caller holding the stub row's digest should pass it and get the
        stronger guarantee.
        """
        async with self._client() as s3:
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
        record = ArchivedRecord(key=key, payload=payload, digest=expected_digest or stored)
        record.verify()
        return record

    async def exists(self, key: str) -> bool:
        async with self._client() as s3:
            try:
                await s3.head_object(Bucket=self._bucket, Key=self._object_key(key))
            except ClientError as exc:
                if exc.response.get("Error", {}).get("Code") not in _MISSING_CODES:
                    raise
                # A HEAD carries no body, so a missing *bucket* and a missing
                # *key* both come back as a bare 404 — dropping `NoSuchBucket`
                # from the missing codes fixes `get` (which uses `get_object`
                # and gets the real code) and cannot fix this one. So confirm
                # the bucket before reporting absence. The extra round trip is
                # only on the miss path, which is exactly where "no" must mean
                # "not there" rather than "could not look".
                await s3.head_bucket(Bucket=self._bucket)
                return False
            return True

    async def list_keys(self, prefix: str = "") -> AsyncIterator[str]:
        async with self._client() as s3:
            paginator = s3.get_paginator("list_objects_v2")
            # Paginated rather than a single list_objects_v2 call, which caps at
            # 1000 keys and reports no error when it truncates. An archive is
            # the one tier expected to exceed that.
            # The trailing slash is what keeps the namespace a namespace. Bare
            # `Prefix=self._prefix` is a string match, so a store rooted at
            # `archive` also listed `archive-old/run` — and `_strip_prefix` then
            # cut a fixed number of characters off it and reported the key as
            # `old/run`, inventing a record that does not exist.
            if prefix:
                scope = self._object_key(prefix)
            elif self._prefix:
                scope = f"{self._prefix}/"
            else:
                scope = ""
            async for page in paginator.paginate(Bucket=self._bucket, Prefix=scope):
                for obj in page.get("Contents", []):
                    yield self._strip_prefix(obj["Key"])

    async def delete(self, key: str) -> bool:
        existed = await self.exists(key)
        async with self._client() as s3:
            # S3 DELETE is unconditionally successful, so the HEAD above is what
            # makes the "was it there" answer real rather than always True.
            await s3.delete_object(Bucket=self._bucket, Key=self._object_key(key))
        return existed

    async def ensure_bucket(self) -> None:
        """Create the bucket if absent. For tests and first-run setup."""
        async with self._client() as s3:
            try:
                await s3.head_bucket(Bucket=self._bucket)
            except ClientError:
                # AWS rejects a bare create outside us-east-1 and requires the
                # region as an explicit LocationConstraint — and rejects the
                # constraint *for* us-east-1, which is why this is a branch and
                # not an unconditional argument. S3-compatible servers such as
                # MinIO accept either form, so the AWS rule decides.
                region = self._client_kwargs.get("region_name")
                if region and region != "us-east-1":
                    await s3.create_bucket(
                        Bucket=self._bucket,
                        CreateBucketConfiguration={"LocationConstraint": region},
                    )
                else:
                    await s3.create_bucket(Bucket=self._bucket)
