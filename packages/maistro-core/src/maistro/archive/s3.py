"""S3-compatible object storage as the archive tier (ADR-082226-f436).

Not an AWS assumption. `endpoint_url` is a first-class parameter, so MinIO,
Cloudflare R2, Backblaze B2, Ceph and Wasabi are all supported the same way —
hard-coding AWS would make the homelab deployment buy a cloud account to use its
own NAS, which is the opposite of what a storage tier is for.

boto3 is imported **inside the constructor**, not at module scope. ADR decision
4 makes that a rule rather than a style: `maistro-core` is a library other
products import (ADR-019), and a transitive boto3 is a large, opinionated
dependency to inflict on a consumer that wanted a router. A deployment that does
not archive to S3 never imports it, and `maistro.archive` imports cleanly with
the extra absent.

The calls are synchronous boto3 run in a worker thread rather than aioboto3.
That is a deliberate trade: aioboto3 would be a second, less-used dependency for
an operation whose defining property is that it happens rarely, and the thread
hop is irrelevant next to the network round trip.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any

from maistro.archive.filesystem import verify
from maistro.archive.types import ArchivedRecordNotFound, ArchiveError, ArchiveKey

logger = logging.getLogger("maistro.archive.s3")

#: Install hint used when the extra is missing. Named here so the message is the
#: same wherever it surfaces.
S3_EXTRA_HINT = "install the 's3' extra: pip install 'maistro-core[s3]'"


class S3ArchiveStore:
    """Content-addressed objects in an S3-compatible bucket."""

    def __init__(
        self,
        bucket: str,
        *,
        endpoint_url: str | None = None,
        region_name: str | None = None,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        page_size: int | None = None,
        client: Any = None,
    ) -> None:
        """Bind to a bucket.

        Credentials are parameters rather than environment reads because they
        come from the vault (ADR decision 8, SPEC-011), not from ambient config.
        Passing none of them falls back to boto3's own resolution chain, which is
        correct on an instance with a role attached.

        `page_size` caps the keys `list_scope` asks for per request. Left at
        `None` the service decides (1000 on every implementation seen), which is
        the right default: a scope is listed rarely and a smaller page only buys
        more round trips. It is a parameter because the continuation loop is
        otherwise unobservable below a thousand objects — an operator tuning
        memory per page and a test proving the loop actually follows the token
        want the same knob.

        `client` is for tests and for a caller that has already built a
        configured client; supplying it skips the boto3 import entirely.
        """
        if not bucket.strip():
            raise ArchiveError("bucket must be a non-empty string")
        if page_size is not None and page_size < 1:
            raise ArchiveError(f"page_size must be at least 1, not {page_size}")
        self._bucket = bucket
        self._page_size = page_size
        if client is not None:
            self._client = client
            return
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - exercised by the absence test
            raise ArchiveError(f"S3ArchiveStore needs boto3; {S3_EXTRA_HINT}") from exc
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region_name,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
        )

    def _is_missing(self, exc: Exception) -> bool:
        """Whether a botocore error means "no such object".

        Matched on the error code rather than the exception class: botocore
        generates its exception types per client, so `client.exceptions.NoSuchKey`
        is not importable and is not the same object across clients. head_object
        answers 404 where get_object answers NoSuchKey, and both must count.
        """
        response = getattr(exc, "response", None)
        if not isinstance(response, dict):
            return False
        error = response.get("Error", {})
        return str(error.get("Code", "")) in {"NoSuchKey", "404", "NotFound"}

    async def put(self, payload: bytes, *, scope: str) -> ArchiveKey:
        key = ArchiveKey.for_payload(payload, scope=scope)
        await asyncio.to_thread(
            self._client.put_object, Bucket=self._bucket, Key=str(key), Body=payload
        )
        return key

    async def get(self, key: ArchiveKey) -> bytes:
        payload = await asyncio.to_thread(self._get_bytes, key)
        verify(key, payload)
        return payload

    def _get_bytes(self, key: ArchiveKey) -> bytes:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=str(key))
        except Exception as exc:
            if self._is_missing(exc):
                raise ArchivedRecordNotFound(str(key)) from exc
            raise
        body = response["Body"]
        try:
            data = body.read()
        finally:
            close = getattr(body, "close", None)
            if close is not None:
                close()
        return bytes(data)

    async def exists(self, key: ArchiveKey) -> bool:
        return await asyncio.to_thread(self._head, key)

    def _head(self, key: ArchiveKey) -> bool:
        try:
            self._client.head_object(Bucket=self._bucket, Key=str(key))
        except Exception as exc:
            if self._is_missing(exc):
                self._require_bucket(exc)
                return False
            raise
        return True

    def _require_bucket(self, cause: Exception) -> None:
        """Refuse to read a 404 as "no such record" when the bucket is gone.

        `head_object` answers a bare `404` with no error code, and it answers
        the same 404 whether the key is absent from a healthy bucket or the
        bucket itself does not exist — verified against a live server, where
        the two responses are byte-identical apart from the request id. `get`
        is not exposed to this (`get_object` distinguishes `NoSuchKey` from
        `NoSuchBucket`), so this is `exists()`'s problem alone.

        Getting it wrong is the failure decision 6 of the ADR exists to
        prevent: a misconfigured bucket name, a deleted bucket or a credential
        that can no longer see it would report every archived record as
        absent — an outage indistinguishable from deletion, in the tier least
        likely to be watched.

        One extra call, and only on a miss. A hit never pays it, and a miss is
        the case where being wrong is expensive.
        """
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except Exception as exc:
            raise ArchiveError(
                f"archive bucket {self._bucket!r} is not reachable, so whether "
                f"this object exists is unknown; refusing to report it absent"
            ) from exc

    async def list_scope(self, scope: str) -> AsyncIterator[ArchiveKey]:
        """Every key under `scope`, one page at a time.

        `list_objects_v2` caps a response at 1000 keys and hands back a
        continuation token, so a scope larger than that is only fully listed by
        following it — a single call would silently return a prefix of the
        answer, which is worse than a slow one. Each page is fetched on a
        worker thread and yielded before the next is requested, so a caller
        that stops early stops the paging with it.
        """
        # Constructed rather than concatenated, so an unsafe scope is refused
        # by `ArchiveKey`'s own validation before it reaches the bucket.
        prefix = f"{ArchiveKey(scope=scope, digest='0' * 64).scope}/"
        token: str | None = None
        while True:
            page = await asyncio.to_thread(self._page, prefix, token)
            for entry in page.get("Contents", ()):
                name = str(entry.get("Key", ""))
                try:
                    yield ArchiveKey.parse(name)
                except ArchiveError:
                    # Something else put an object here whose name is not a
                    # key. Skipped rather than raised: one foreign object must
                    # not make the whole scope unlistable.
                    logger.warning("skipping unparseable archive object %r", name)
            token = page.get("NextContinuationToken")
            if not page.get("IsTruncated") or not token:
                return

    def _page(self, prefix: str, token: str | None) -> dict[str, Any]:
        request: dict[str, Any] = {"Bucket": self._bucket, "Prefix": prefix}
        if self._page_size is not None:
            request["MaxKeys"] = self._page_size
        if token:
            request["ContinuationToken"] = token
        return dict(self._client.list_objects_v2(**request))

    async def delete(self, key: ArchiveKey) -> None:
        # S3 delete is already idempotent — deleting an absent key succeeds —
        # which matches the protocol's contract without special-casing.
        await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=str(key))


__all__ = ["S3_EXTRA_HINT", "S3ArchiveStore"]
