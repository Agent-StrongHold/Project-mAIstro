"""One place that decides whether a principal may see a stored record (#312).

The chat routes read `stores.chat_sessions` as a global dictionary. Every
handler was correct about *what* it did and silent about *whose* data it did
it to, so any authenticated user could list, read, append to, or delete any
other user's chat by id. The model already carried a `user_id` field; nothing
ever wrote it and nothing ever read it.

The fix is not "add a check to each handler" — that is the shape that decays,
because the next handler added is the one that forgets. Handlers take an
`OwnedStore` instead of the raw store, and an `OwnedStore` has no operation
that can reach a record belonging to someone else.
`scripts/check-owned-store-access.py` keeps the raw store out of the route
modules, so the omission is a failed gate rather than a quiet leak.

Two rules the view enforces that a hand-written check usually gets wrong:

**Absent and forbidden are the same answer.** `require()` raises the same 404,
with the same body, for a session that does not exist and for one that belongs
to someone else. A 403 on the second is an existence oracle: it turns id
guessing into an enumeration of who has how many chats.

**A record with no owner belongs to no one.** Rows written before ownership
was bound carry `user_id == ""`. `owns()` compares against the requester's id,
which is never empty, so those rows are invisible to every principal rather
than visible to all of them. That is the quarantine disposition #312 asks for:
they stay on disk, addressable by an operator with database access, and
unreachable through the API. Nothing deletes them, because deleting a user's
history to fix a bug in our bookkeeping is the worse failure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import HTTPException

#: The `user_id` a record written before #312 carries. Not a sentinel anyone
#: writes deliberately — it is the field default, which is exactly why it must
#: never compare equal to a real owner.
UNOWNED = ""


class _Owned(Protocol):
    """The one field this module needs a stored record to have."""

    user_id: str


@dataclass(frozen=True)
class Owner:
    """The authenticated principal, reduced to what an ownership test needs.

    Just the id. Role does not appear because it plays no part in this
    decision: `AuthMiddleware` refuses the whole `/v1/chat/` surface to the
    admin role, so there is no admin-sees-everything branch here to get wrong.
    A future surface that does need one should add it deliberately, with its
    own tests, rather than inherit a field that happened to be in scope.
    """

    id: str


def owner_of(request: Any) -> Owner:
    """The principal `AuthMiddleware` attached, or 401.

    The middleware rejects an unauthenticated `/v1/` request before any handler
    runs, so reaching here without `request.state.user` means the route escaped
    it — a new public prefix, a router mounted outside `/v1/`. Failing closed
    keeps that mistake from silently handing one caller's records to whoever
    asks first.
    """
    user = getattr(request.state, "user", None)
    if not isinstance(user, dict):
        raise HTTPException(status_code=401, detail="Authentication required")
    user_id = str(user.get("id") or "")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    return Owner(id=user_id)


class OwnedStore:
    """A `ModelStore` seen through one owner's eyes.

    Every method is scoped. There is deliberately no escape hatch — no
    `raw`, no `all()`, no key-based `__getitem__` — because an escape hatch is
    what the next handler reaches for.
    """

    def __init__(self, store: Any, owner: Owner, *, missing_detail: str = "not found") -> None:
        self._store = store
        self._owner = owner
        self._missing_detail = missing_detail

    @property
    def owner_id(self) -> str:
        """For the few callers that must name the owner — seeding a starter
        record for them, say — rather than merely filter by it."""
        return self._owner.id

    def owns(self, record: _Owned) -> bool:
        """`UNOWNED` never matches: `Owner.id` is non-empty by construction."""
        return getattr(record, "user_id", UNOWNED) == self._owner.id

    def values(self) -> list[Any]:
        """Only this owner's records, in store order."""
        return [record for record in self._store.values() if self.owns(record)]

    def require(self, key: str) -> Any:
        """The record, or the same 404 for missing and for not-yours."""
        record = self._store.get(key)
        if record is None or not self.owns(record):
            raise HTTPException(status_code=404, detail=self._missing_detail)
        return record

    def create(self, key: str, record: Any) -> Any:
        """Store `record` with ownership stamped from the session, not the body.

        The copy is the point: whatever `user_id` arrived on the model — a
        client that guessed the field name, a stale object rebuilt from an old
        row — is overwritten by the authenticated principal before the write.
        """
        stamped = record.model_copy(update={"user_id": self._owner.id})
        self._store[key] = stamped
        return stamped

    def discard(self, key: str) -> None:
        """Remove the record if it is this owner's; otherwise do nothing.

        Silence in both directions, for the same reason `require` raises the
        same 404: a delete that reported whether something was there is an
        oracle even when it refuses to act.
        """
        record = self._store.get(key)
        if record is not None and self.owns(record):
            self._store.pop(key, None)

    def persist(self, key: str) -> None:
        """Flush a record this owner holds; 404 if they do not hold it."""
        self.require(key)
        self._store.persist(key)


#: The 404 body every chat-session route returns, for a session that is absent
#: and for one that belongs to someone else alike.
_SESSION_MISSING = "session not found"


def owned_chat_sessions(owner: Owner) -> OwnedStore:
    """The chat store, scoped to `owner`.

    The binding of store to view lives here rather than in each caller so that
    `scripts/check-owned-store-access.py` can require it: no route module names
    `stores.chat_sessions` at all, so none of them can name it *unscoped*.
    """
    import stores

    return OwnedStore(stores.chat_sessions, owner, missing_detail=_SESSION_MISSING)


def chat_sessions_for(request: Any) -> OwnedStore:
    """The chat store, scoped to whoever is making this request."""
    return owned_chat_sessions(owner_of(request))
