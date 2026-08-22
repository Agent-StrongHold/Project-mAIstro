"""Archive-tier object storage — the cold layer below durable memory (ADR-082226-d3dd).

`ADR-082226-5104` decision 8 ends its memory hierarchy at "long-term:
PostgreSQL + pgvector, durable". That word carries too much: everything ever
true stays in the row store forever, at row-store cost, competing for the same
buffer cache and backup window as the working set. Decision 11 already sends
large *artifacts* to object storage; this is the same argument applied to *cold*
records.

An archived record is still authoritative. This is not a backup and not a
replacement for PostgreSQL as the system of record — the record has moved to
storage priced for reading it rarely.

Two rules shape the protocol, both from the ADR:

- **A read never returns emptiness.** `get` raises `RecordArchivedError`'s
  sibling `ArchiveKeyNotFoundError` when a key is genuinely absent, and returns
  bytes otherwise. It must never answer "nothing here" in a way a caller could
  mistake for "no such record" — silent degradation in the layer least likely to
  be looked at is what makes an archive unsafe to enable.
- **Content-addressed.** `put` returns the payload digest and is idempotent:
  writing the same bytes to the same key is a no-op rather than a second object.
  The digest is what makes "archive, read back, byte-identical" checkable rather
  than asserted.

Implementations live in `maistro.memory.archive`. `FilesystemArchiveStore` has
no third-party dependency; `S3ArchiveStore` sits behind the `maistro-core[s3]`
extra and is imported lazily, so a deployment that does not archive never pays
for a cloud SDK.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

#: Digest algorithm for content addressing. Named once so the stub column, the
#: protocol and both implementations cannot disagree about it.
DIGEST_ALGORITHM = "sha256"


def content_digest(payload: bytes) -> str:
    """The content address of a payload, as ``sha256:<hex>``.

    Prefixed with the algorithm rather than left as a bare hex string: a stub
    row storing a bare digest cannot be re-verified after the algorithm changes,
    and "the digest does not match" is indistinguishable from "the digest is a
    different function" at exactly the moment that distinction matters.
    """
    return f"{DIGEST_ALGORITHM}:{hashlib.sha256(payload).hexdigest()}"


@dataclass(frozen=True)
class ArchivedRecord:
    """What an archive holds for one key."""

    key: str
    payload: bytes
    digest: str

    def verify(self) -> None:
        """Raise if the payload does not match the digest it arrived with.

        Called on every read. An object store that silently returned truncated
        or wrong bytes would otherwise rehydrate a record that reads as
        authoritative — which is worse than a failed read, because the caller
        has no reason to doubt it.
        """
        actual = content_digest(self.payload)
        if actual != self.digest:
            raise ArchiveDigestMismatchError(self.key, expected=self.digest, actual=actual)


class ArchiveError(Exception):
    """Base for every archive-tier failure."""


class ArchiveKeyNotFoundError(ArchiveError):
    """No object under this key.

    Distinct from "the record is archived": this means the archive itself does
    not have it, which is a consistency failure between the stub row and the
    object store rather than an ordinary miss.
    """

    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"no archived object under key {key!r}")


class ArchiveDigestMismatchError(ArchiveError):
    """The bytes read back are not the bytes written."""

    def __init__(self, key: str, *, expected: str, actual: str) -> None:
        self.key = key
        self.expected = expected
        self.actual = actual
        super().__init__(f"archived object {key!r} failed digest check: {expected} != {actual}")


class RecordArchivedError(ArchiveError):
    """Raised by a *store* asked for a record whose payload has been archived.

    The decision this type exists for (ADR-082226-d3dd §3): a read for an
    archived record returns it or says it is archived, and never an empty result
    that reads as "no such record". Callers that can rehydrate catch this and
    fetch `key` from the archive; callers that cannot get an error naming
    exactly what happened instead of a null.
    """

    def __init__(self, record_id: str, key: str) -> None:
        self.record_id = record_id
        self.key = key
        super().__init__(
            f"record {record_id!r} is archived at {key!r}; fetch it from the archive store "
            f"to rehydrate, or query the stub row for identity only"
        )


@runtime_checkable
class ArchiveStore(Protocol):
    """Put, get, list and delete archived payloads by stable key.

    Keys are `{kind}/{id}` — one object per record, per ADR-082226-d3dd §4.
    Batching by time window is cheaper to write and worse to read back one
    record, and the write path is the one that is already cheap: it is a
    background sweep with nobody waiting on it, while a read is a person asking
    what happened in a Run.
    """

    async def put(self, key: str, payload: bytes) -> str:
        """Store `payload` under `key`; return its content digest.

        Idempotent: writing bytes that are already there under the same key is a
        no-op. Re-running an interrupted archive sweep must not duplicate
        objects or change digests.
        """
        ...

    async def get(self, key: str) -> ArchivedRecord:
        """Read back one archived payload, digest-verified.

        Raises:
            ArchiveKeyNotFoundError: nothing is stored under `key`.
            ArchiveDigestMismatchError: the bytes do not match their digest.
        """
        ...

    async def exists(self, key: str) -> bool:
        """Whether an object is stored under `key`, without transferring it."""
        ...

    def list_keys(self, prefix: str = "") -> AsyncIterator[str]:
        """Every key under `prefix`, lexicographically.

        An iterator rather than a list: an archive is the one tier expected to
        outgrow memory, and a `list_keys()` that materialises the whole bucket
        is a gate that works until the day it matters.
        """
        ...

    async def delete(self, key: str) -> bool:
        """Remove one object; return whether it was there.

        Deleting an archived record is a retention decision with legal and
        provenance dimensions, deliberately left out of ADR-082226-d3dd. This
        exists so an implementation is complete and testable, not as an
        endorsement of calling it on live data.
        """
        ...
