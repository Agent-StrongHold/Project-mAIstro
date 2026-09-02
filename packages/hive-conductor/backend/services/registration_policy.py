"""Registration policy — who may create the next account (#313).

``routes/auth.py`` used to answer ``_registration_allowed() =
len(stores.users) > 0``. The register route is unauthenticated, so the
moment setup created the first owner, public signup went from *closed*
(bootstrap unfinished) to *open forever*: completing initial setup enabled
the exact thing it should have closed.

The policy here inverts the default. Registration is closed unless a durable
record says otherwise:

* **closed** — the default, and the only state a missing, unreadable, or
  corrupt record can produce. No anonymous account creation. Setup is the
  only path that mints the first owner, exactly once.
* **open** — an administrator set it deliberately, after setup. Durable, so
  a restart neither re-opens a closed hive nor silently closes an opened
  one.
* **invitation** — a single-use, expiring token an administrator issues.
  Whether an invitation is *spent* is decided by one conflict-safe insert
  (``JsonStore.put_if_absent``, whose durable half is the SQLite primary
  key), so the same code cannot create two accounts even when two requests
  present it concurrently — the same primitive the OAuth identity linker
  relies on for the same reason.

Fail-closed is structural, not a check somebody has to remember to call:
nothing in a partial initialization can produce ``open``, because ``open``
is a value only an authenticated administrator writes, and every write goes
through the acknowledgement rule below — acknowledged only after the stored
record reads back byte-for-byte as what was sent (the rule
``services/settings_store.py`` established for #334, when a best-effort
write was found reporting success for state that never landed).

The invitations themselves are insert-only records in
``stores.registration_invitations``. Tokens are 256-bit urlsafe values
stored as SHA-256 digests, so the durable rows cannot be read back out as
usable invitations; the digest is also the key, which is what makes
redemption one atomic insert instead of a read-decide-write race.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

logger = logging.getLogger("hive.registration_policy")

#: One namespace, one key: the policy is a single document.
STORE_NAME = "registration_policy"
RECORD_KEY = "current"

#: The envelope shape this build writes and is willing to read. A stored
#: record at any other shape is treated as corrupt — read as "closed" —
#: rather than coerced, because a coerced record is a policy nobody set.
SCHEMA_VERSION = 1

MODE_CLOSED = "closed"
MODE_OPEN = "open"
MODES = frozenset({MODE_CLOSED, MODE_OPEN})

_INVITATION_KEY_PREFIX = "inv:"
_REDEEMED_KEY_PREFIX = "used:"
#: `secrets.token_urlsafe(32)` is 43 chars; the bound exists so a bogus
#: cookie-sized blob is rejected before it reaches the hash, and so tests
#: can say "too long" without generating one.
_TOKEN_BYTES = 32
_TOKEN_MAX_LENGTH = 128
_TOKEN_ALPHABET = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")

DEFAULT_INVITATION_TTL_SECONDS = 7 * 24 * 3600
MIN_INVITATION_TTL_SECONDS = 300
MAX_INVITATION_TTL_SECONDS = 30 * 24 * 3600
NOTE_MAX_LENGTH = 200


class RegistrationPolicyError(RuntimeError):
    """A policy write was not observed in the store afterwards.

    Raised for a write that did not land and a read-back that disagreed
    with what was sent. Both mean the same thing to a caller: do not tell
    anyone this succeeded.
    """


def _now() -> datetime:
    """The policy clock. A seam, so expiry is testable without sleeping."""
    return datetime.now(UTC)


# --- The durability seam ---------------------------------------------------
#
# The same arrangement as services/settings_store.py: a Protocol with an
# in-process implementation and a persisted one, `configure()` called once at
# startup, `reset()` for tests and re-initialisation. The persisted write
# drains the writer queue before returning, because `PersistedStore.put_raw`
# only enqueues — an acknowledgement that outruns the write is the exact
# defect #334 documented.


class RegistrationRecordStore(Protocol):
    @property
    def durable(self) -> bool:
        """Whether a write here is expected to survive the process."""

    def read(self) -> str | None:
        """The stored JSON document, or None when nothing is stored."""

    def write(self, document: str) -> None:
        """Submit `document` and return once it is as durable as this store gets."""


class EphemeralRegistrationRecordStore:
    """In-process record store, labelled as such.

    Tests and `memory://` runs go through the identical write-and-read-back
    path, but `durable` is False and the API says so rather than letting an
    in-memory write wear the shape of a durable one.
    """

    def __init__(self) -> None:
        self._document: str | None = None

    @property
    def durable(self) -> bool:
        return False

    def read(self) -> str | None:
        return self._document

    def write(self, document: str) -> None:
        self._document = document


class PersistedRegistrationRecordStore:
    """Record store over `PersistedStore`, draining the writer queue on write."""

    def __init__(self, persisted: Any, flush: Any, timeout: float = 10.0) -> None:
        self._persisted = persisted
        self._flush = flush
        self._timeout = timeout

    @property
    def durable(self) -> bool:
        return True

    def read(self) -> str | None:
        document = self._persisted.get_raw(STORE_NAME, RECORD_KEY)
        return str(document) if document is not None else None

    def write(self, document: str) -> None:
        self._persisted.put_raw(STORE_NAME, RECORD_KEY, document)
        self._flush(timeout=self._timeout)


_store: RegistrationRecordStore = EphemeralRegistrationRecordStore()


def configure(store: RegistrationRecordStore) -> None:
    """Install the record store. Called once, at startup."""
    global _store
    _store = store


def reset(*, store: RegistrationRecordStore | None = None) -> None:
    """Return the module to a fresh state. For tests and re-initialisation."""
    global _store
    _store = store if store is not None else EphemeralRegistrationRecordStore()


def durable() -> bool:
    """Whether the configured store is expected to outlive the process."""
    return _store.durable


# --- The policy ------------------------------------------------------------


@dataclass(frozen=True)
class RegistrationDecision:
    """Whether one registration attempt may proceed, and why.

    `reason` is a machine-readable category for the audit log, never for the
    anonymous response: the HTTP answers are uniform on purpose (#366), and
    distinguishing "expired" from "already used" from "never issued" to a
    stranger is an enumeration primitive, however small.
    """

    allowed: bool
    mode: str
    reason: str
    invitation_id: str | None = None


def _decode(document: str | None) -> dict[str, Any] | None:
    """Parse a stored policy record, or None when it cannot be trusted.

    Every corrupt shape — non-JSON, non-object, wrong schema version, unknown
    mode — collapses to None, and None reads as `closed`. A policy record
    that cannot be validated is a policy nobody set.
    """
    if document is None:
        return None
    try:
        raw = json.loads(document)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(raw, dict):
        return None
    if raw.get("schema_version") != SCHEMA_VERSION:
        return None
    if raw.get("mode") not in MODES:
        return None
    return raw


def _load() -> tuple[dict[str, Any] | None, bool, bool]:
    """`(record, valid, present)` — record is None when absent or corrupt.

    `valid` is False only for a present-but-unreadable record, and `present`
    distinguishes "no policy was ever written" from "one was written and
    cannot be read", so the admin view can say which while everyone else
    simply experiences `closed`.
    """
    document = _store.read()
    if document is None:
        return None, True, False
    record = _decode(document)
    if record is None:
        logger.warning(
            "registration policy record is unreadable; failing closed (mode=%s)", MODE_CLOSED
        )
        return None, False, True
    return record, True, True


def _invitation_store() -> Any:
    # Read at call time so tests (and a Foundation re-initialisation) can
    # swap in a persisted store without re-importing this module.
    import stores

    return stores.registration_invitations


def _bootstrap_complete() -> bool:
    """Whether initial setup has produced an account at all.

    Registration must never mint the *first* owner (#313): bootstrap belongs
    to the one-shot setup state alone, so even a forced `open` record is
    inert until at least one account exists.
    """
    import stores

    return len(stores.users) > 0


def _token_id(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _token_wellformed(token: str) -> bool:
    if not token or len(token) > _TOKEN_MAX_LENGTH:
        return False
    return all(ch in _TOKEN_ALPHABET for ch in token)


def current_mode() -> str:
    """The active mode. Absent or corrupt records read as `closed`."""
    record, _valid, _present = _load()
    if record is None:
        return MODE_CLOSED
    return record["mode"]


def public_view() -> dict[str, Any]:
    """What an unauthenticated caller may learn about the policy: the mode.

    Nothing else. Not how many accounts exist, not who administers them, not
    whether the stored record is corrupt — the login surface needs exactly
    one bit ("may a signup form exist without an invitation?") and that bit
    is already implied by the mode the product publishes.
    """
    return {"mode": current_mode()}


def describe() -> dict[str, Any]:
    """The admin view: the mode, its provenance, and the record's health."""
    record, valid, present = _load()
    invitations = list_invitations()
    return {
        "mode": record["mode"] if record is not None else MODE_CLOSED,
        "updated_at": record.get("updated_at") if record is not None else None,
        "updated_by": record.get("updated_by") if record is not None else None,
        "durable": durable(),
        "record_present": present,
        "record_valid": valid,
        "pending_invitations": sum(1 for invitation in invitations if not invitation["redeemed"]),
    }


def _write_record(mode: str, *, actor: str) -> None:
    """Write the policy record and acknowledge it only once observed.

    The acknowledgement is a read-back comparison, not a returned flag: a
    write that lands differently from what was sent (a torn migration, a
    store that silently no-ops) must not be reported as the mode it claims.
    """
    record = {
        "schema_version": SCHEMA_VERSION,
        "mode": mode,
        "updated_at": _now().isoformat(),
        "updated_by": actor,
    }
    document = json.dumps(record, sort_keys=True)
    _store.write(document)
    if _store.read() != document:
        raise RegistrationPolicyError(
            f"registration policy write was not observed (intended mode {mode!r})"
        )


def set_mode(mode: str, *, actor: str) -> dict[str, Any]:
    """Set the mode durably. `describe()` of the resulting state.

    Raises ValueError for a mode this build does not know — an unknown mode
    is a typo or a newer build's value, and storing it would make this build
    read the record as corrupt (i.e. closed) while claiming it set it.
    """
    if mode not in MODES:
        raise ValueError(f"unknown registration mode {mode!r}; expected one of {sorted(MODES)}")
    _write_record(mode, actor=actor)
    logger.info("registration policy mode set to %s by %s", mode, actor)
    return describe()


def close_after_setup() -> None:
    """The setup wizard's close-out write: registration goes closed, durably.

    Called by `routes/setup.py` before setup reports success, so the
    transition bootstrap→steady-state is recorded by the same authority the
    admin route uses, and an instance that finished setup has a policy
    record even if no administrator ever touches one.
    """
    _write_record(MODE_CLOSED, actor="setup")


def issue_invitation(
    *,
    actor: str,
    ttl_seconds: int | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Mint one single-use invitation token.

    The token is returned exactly once and stored only as a SHA-256 digest;
    the durable rows cannot be read back out as usable invitations. Raises
    ValueError for out-of-range ttl or an over-long note.
    """
    if ttl_seconds is None:
        ttl = DEFAULT_INVITATION_TTL_SECONDS
    else:
        if not isinstance(ttl_seconds, int) or isinstance(ttl_seconds, bool):
            raise ValueError("ttl_seconds must be an integer number of seconds")
        if not MIN_INVITATION_TTL_SECONDS <= ttl_seconds <= MAX_INVITATION_TTL_SECONDS:
            raise ValueError(
                f"ttl_seconds must be between {MIN_INVITATION_TTL_SECONDS} and "
                f"{MAX_INVITATION_TTL_SECONDS}"
            )
        ttl = ttl_seconds
    if note is not None:
        note = note.strip()
        if len(note) > NOTE_MAX_LENGTH:
            raise ValueError(f"note must be at most {NOTE_MAX_LENGTH} characters")

    store = _invitation_store()
    now = _now()
    expires_at = now + timedelta(seconds=ttl)
    for _ in range(5):
        token = secrets.token_urlsafe(_TOKEN_BYTES)
        digest = _token_id(token)
        record = {
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
            "created_by": actor,
            "note": note,
        }
        # Insert-only, decided by the store's conflict rule: a digest
        # collision (two tokens hashing alike) regenerates rather than
        # overwrites, though 256 bits make it a formality.
        if store.put_if_absent(f"{_INVITATION_KEY_PREFIX}{digest}", record):
            return {
                "token": token,
                "invitation_id": digest[:8],
                "expires_at": expires_at.isoformat(),
                "ttl_seconds": ttl,
            }
    raise RegistrationPolicyError("could not allocate a unique invitation id")


def _invitation_record(token: str) -> dict[str, Any] | None:
    """The stored record for `token`, or None when absent or unreadable."""
    store = _invitation_store()
    record = store.get(f"{_INVITATION_KEY_PREFIX}{_token_id(token)}")
    if not isinstance(record, dict):
        return None
    return record


def _invitation_state(token: str) -> tuple[dict[str, Any] | None, str]:
    """`(record, state)` where state is one of pending/expired/redeemed/absent."""
    record = _invitation_record(token)
    if record is None:
        return None, "absent"
    if f"{_REDEEMED_KEY_PREFIX}{_token_id(token)}" in _invitation_store():
        return record, "redeemed"
    expires_at = record.get("expires_at")
    try:
        expires = datetime.fromisoformat(str(expires_at))
    except (TypeError, ValueError):
        # An unreadable expiry is not a reason to accept the token.
        return record, "expired"
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if _now() >= expires:
        return record, "expired"
    return record, "pending"


def evaluate_registration(token: str | None = None) -> RegistrationDecision:
    """May this anonymous attempt create an account? Check only — no side effects.

    Redemption is a separate, atomic step (`redeem_invitation`) so that
    checking never spends anything: the route checks, then pays exactly once
    on the path that creates the account.
    """
    mode = current_mode()
    if mode == MODE_OPEN and _bootstrap_complete():
        return RegistrationDecision(allowed=True, mode=mode, reason="open")
    trimmed = (token or "").strip()
    if trimmed:
        if not _token_wellformed(trimmed):
            return RegistrationDecision(allowed=False, mode=mode, reason="invalid_invitation")
        if not _bootstrap_complete():
            # An invitation must never mint the first owner either (#313).
            return RegistrationDecision(allowed=False, mode=mode, reason="bootstrap_incomplete")
        _record, state = _invitation_state(trimmed)
        if state != "pending":
            return RegistrationDecision(allowed=False, mode=mode, reason="invalid_invitation")
        return RegistrationDecision(
            allowed=True,
            mode=mode,
            reason="invitation",
            invitation_id=_token_id(trimmed)[:8],
        )
    reason = "bootstrap_incomplete" if mode == MODE_OPEN else "closed"
    return RegistrationDecision(allowed=False, mode=mode, reason=reason)


def redeem_invitation(token: str, *, username: str) -> bool:
    """Spend `token` for `username`. True exactly once per token, ever.

    The decision is one conflict-safe insert of the redemption marker, so
    concurrent presentations of the same token produce exactly one winner —
    in-process races and multi-writer durable stores alike. Called by the
    register route *before* the account row is written: if the insert loses,
    no account is created, and if anything after it fails the token stays
    spent (fail-closed; an operator reissues).
    """
    trimmed = (token or "").strip()
    if not _token_wellformed(trimmed):
        return False
    digest = _token_id(trimmed)
    _record, state = _invitation_state(trimmed)
    if state != "pending":
        return False
    store = _invitation_store()
    return bool(
        store.put_if_absent(
            f"{_REDEEMED_KEY_PREFIX}{digest}",
            {"redeemed_at": _now().isoformat(), "redeemed_by_username": username},
        )
    )


def list_invitations() -> list[dict[str, Any]]:
    """The admin listing: statuses and metadata, never tokens or digests.

    Sorted newest-first, and capped by nothing because the store only ever
    holds what an administrator deliberately issued.
    """
    store = _invitation_store()
    now = _now()
    views: list[dict[str, Any]] = []
    for key, record in store.items():
        if not key.startswith(_INVITATION_KEY_PREFIX):
            continue
        if not isinstance(record, dict):
            continue
        digest = key[len(_INVITATION_KEY_PREFIX) :]
        redeemed_at = None
        redeemed_record = store.get(f"{_REDEEMED_KEY_PREFIX}{digest}")
        if isinstance(redeemed_record, dict):
            redeemed_at = redeemed_record.get("redeemed_at")
        expires_at = record.get("expires_at")
        expired = False
        try:
            expires = datetime.fromisoformat(str(expires_at))
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=UTC)
            expired = now >= expires
        except (TypeError, ValueError):
            expired = True
        views.append(
            {
                "invitation_id": digest[:8],
                "created_at": record.get("created_at"),
                "created_by": record.get("created_by"),
                "expires_at": expires_at,
                "expired": expired and redeemed_at is None,
                "redeemed": redeemed_at is not None,
                "redeemed_at": redeemed_at,
                "note": record.get("note"),
            }
        )
    views.sort(key=lambda view: str(view.get("created_at") or ""), reverse=True)
    return views
