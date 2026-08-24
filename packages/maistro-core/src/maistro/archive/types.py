"""Values and failures for the archive tier (ADR-082226-f436).

The tier's defining property is that an archived record is still authoritative —
it moved, it was not backed up and it was not deleted. Every type here exists to
keep that true at the boundary, which mostly means refusing to let "archived"
and "absent" look the same to a caller.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

#: Scope prefixes are path segments in an object key, so they must not smuggle
#: traversal or separators. Deliberately stricter than S3 requires: the
#: filesystem backend turns a key into a path, and `../` there is an escape.
_SCOPE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*(/[a-z0-9][a-z0-9._-]*)*$")


class ArchiveError(Exception):
    """Base for every archive failure."""


class InvalidArchiveScope(ArchiveError, ValueError):
    """The scope prefix is not a safe key segment."""


class ArchivedRecordNotFound(ArchiveError, KeyError):
    """No object exists for this key.

    Distinct from "this record was never archived": a caller holding a key got
    it from a tombstone row that says the payload is there. Raising rather than
    returning empty is decision 6 of the ADR — a silent empty result for a
    record that exists is indistinguishable from deletion.
    """


class ArchiveIntegrityError(ArchiveError):
    """The stored bytes do not hash to the key that addressed them.

    Content addressing is what makes this detectable at all. A backend that
    silently returned corrupted or truncated bytes would hand a caller something
    that looks like the record and is not.
    """


@dataclass(frozen=True)
class ArchiveKey:
    """A content-addressed location: a scope prefix and a digest.

    Content addressing (ADR decision 5) buys two things. Re-archiving an
    unchanged record is a no-op rather than a second copy, and a read can verify
    what it got instead of trusting it.
    """

    scope: str
    digest: str

    def __post_init__(self) -> None:
        if not _SCOPE_PATTERN.match(self.scope):
            raise InvalidArchiveScope(
                f"archive scope {self.scope!r} must be lowercase path segments of "
                f"[a-z0-9._-], with no leading separator and no '..'"
            )
        if not re.fullmatch(r"[0-9a-f]{64}", self.digest):
            raise ArchiveError(f"archive digest {self.digest!r} is not a sha256 hex digest")

    @classmethod
    def for_payload(cls, payload: bytes, *, scope: str) -> ArchiveKey:
        return cls(scope=scope, digest=hashlib.sha256(payload).hexdigest())

    def __str__(self) -> str:
        return f"{self.scope}/{self.digest}"

    @classmethod
    def parse(cls, key: str) -> ArchiveKey:
        scope, _, digest = key.rpartition("/")
        if not scope:
            raise ArchiveError(f"archive key {key!r} has no scope prefix")
        return cls(scope=scope, digest=digest)


__all__ = [
    "ArchiveError",
    "ArchiveIntegrityError",
    "ArchiveKey",
    "ArchivedRecordNotFound",
    "InvalidArchiveScope",
]
