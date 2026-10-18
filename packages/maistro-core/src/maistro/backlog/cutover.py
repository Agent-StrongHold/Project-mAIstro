"""The explicit backlog authority cutover (#102).

Root ``BACKLOG.md`` is the hand-maintained authority until this module's
cutover runs; afterwards the database is authoritative, the Markdown file is
generated documentation, and the cutover itself is a recorded, reversible
event. Three pieces make that more than a convention:

**The authority ledger** is an append-only record of authority revisions —
every flip between ``markdown`` and ``db`` authority is one row with its
revision number, actor, instant and note. The current authority is the latest
revision; reverting is a new revision, never a deletion, so the cutover's
history survives even a revert made during migration validation.

**The document state** holds the parsed token stream (furniture verbatim plus
item positions) that the deterministic export replays. Persisted at import
time, it is what makes an export reproducible after a restart without the
original file — the post-cutover ``BACKLOG.md`` is generated from the
database alone.

**The cutover operation** refuses to flip authority until the replacement
path is proven: it imports the current file, exports the imported state, and
requires byte equality with the original before appending the ``db`` authority
revision. Reverting requires no proof — authority returns to the Markdown
file immediately, and the ledger records that too.

The SQLite control store owns its own tables (``backlog_authority``,
``backlog_documents``) behind the same ``ensure_schema`` discipline as the
item store; PostgreSQL DDL is owned by Alembic migration ``049``.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterable, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final, Protocol

from maistro.backlog.markdown_io import (
    FURNITURE,
    ITEM,
    ParsedDocument,
    effective_status_word,
    is_terminal_word,
    parse_dependencies,
    parse_markdown,
    render_document,
    status_to_structured,
    validate_document,
)
from maistro.backlog.model import BacklogItem, BacklogOrigin, status_is_terminal
from maistro.backlog.store import BacklogStore
from maistro.sqlite_schema import execute_schema_script, serialized_schema_upgrade

if TYPE_CHECKING:  # pragma: no cover - typing only
    import aiosqlite

#: The document the cutover migrates. One root backlog; the id is stable so
#: tooling and the consistency gate agree on what they are talking about.
ROOT_DOCUMENT_ID: Final = "BACKLOG.md"

#: Workspace the imported root backlog lives in. The root backlog is repo-level
#: state; a dedicated workspace keeps it out of any product workspace's way.
ROOT_WORKSPACE_ID: Final = "root-backlog"

#: Actor recorded on import/cutover mutations made by the tooling.
CUTOVER_ACTOR: Final = "backlog-cutover"

#: Heading generated for items created in the database after the cutover; the
#: generated file must have somewhere deterministic to put them.
POST_CUTOVER_HEADING: Final = "## Items added after the authority cutover"


class BacklogAuthority(StrEnum):
    """Which representation is the work-source of record.

    ``markdown``: humans and authorized agents edit ``BACKLOG.md``; the
    database holds a projection kept in sync by importing.
    ``db``: the database is authoritative; the Markdown file is generated
    documentation and direct edits to it are no longer authoritative.
    """

    MARKDOWN = "markdown"
    DB = "db"


def _ensure_utc(value: Any) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AuthorityRecord:
    """One recorded authority revision. Append-only; never rewritten."""

    __slots__ = ("actor", "at", "authority", "note", "revision")

    def __init__(
        self,
        *,
        revision: int,
        authority: BacklogAuthority,
        actor: str,
        at: datetime,
        note: str,
    ) -> None:
        self.revision = revision
        self.authority = authority
        self.actor = actor
        self.at = at
        self.note = note

    def as_dict(self) -> dict[str, object]:
        return {
            "revision": self.revision,
            "authority": self.authority.value,
            "actor": self.actor,
            "at": self.at.isoformat(),
            "note": self.note,
        }

    @classmethod
    def from_row(cls, row: Sequence[Any]) -> AuthorityRecord:
        return cls(
            revision=int(row[0]),
            authority=BacklogAuthority(row[1]),
            actor=str(row[2]),
            at=_ensure_utc(row[3]),
            note=str(row[4]),
        )


class AuthorityLedger(Protocol):
    """The one authority record for one installation."""

    async def ensure_schema(self) -> None: ...

    async def current(self) -> AuthorityRecord | None: ...

    async def append(
        self,
        *,
        authority: BacklogAuthority,
        actor: str,
        note: str,
        at: datetime | None = None,
    ) -> AuthorityRecord: ...

    async def history(self) -> list[AuthorityRecord]: ...


class InMemoryAuthorityLedger:
    """Reference implementation; the durable twins are read against it."""

    def __init__(self) -> None:
        self._records: list[AuthorityRecord] = []

    async def ensure_schema(self) -> None:
        return None

    async def current(self) -> AuthorityRecord | None:
        return self._records[-1] if self._records else None

    async def append(
        self,
        *,
        authority: BacklogAuthority,
        actor: str,
        note: str,
        at: datetime | None = None,
    ) -> AuthorityRecord:
        record = AuthorityRecord(
            revision=len(self._records) + 1,
            authority=authority,
            actor=actor,
            at=at or _utcnow(),
            note=note,
        )
        self._records.append(record)
        return record

    async def history(self) -> list[AuthorityRecord]:
        return list(self._records)


class DocumentState(Protocol):
    """The persisted token stream of one imported document."""

    async def ensure_schema(self) -> None: ...

    async def get_tokens(self, document_id: str) -> tuple[tuple[str, str], ...] | None: ...

    async def put_tokens(self, document_id: str, tokens: Sequence[tuple[str, str]]) -> None: ...


class InMemoryDocumentState:
    """Reference token-stream store paired with the in-memory ledger."""

    def __init__(self) -> None:
        self._tokens: dict[str, tuple[tuple[str, str], ...]] = {}

    async def ensure_schema(self) -> None:
        return None

    async def get_tokens(self, document_id: str) -> tuple[tuple[str, str], ...] | None:
        return self._tokens.get(document_id)

    async def put_tokens(self, document_id: str, tokens: Sequence[tuple[str, str]]) -> None:
        self._tokens[document_id] = tuple(tokens)


_SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS backlog_authority (
    revision INTEGER PRIMARY KEY AUTOINCREMENT,
    authority TEXT NOT NULL,
    actor TEXT NOT NULL,
    at TEXT NOT NULL,
    note TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS backlog_documents (
    document_id TEXT PRIMARY KEY,
    tokens TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class SqliteAuthorityLedger:
    """Durable authority ledger; every append commits before it returns."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn
        self._write_lock = asyncio.Lock()

    async def ensure_schema(self) -> None:
        async with serialized_schema_upgrade(self._conn):
            await execute_schema_script(self._conn, _SQLITE_SCHEMA)

    @asynccontextmanager
    async def _write(self) -> AsyncIterator[aiosqlite.Connection]:
        async with self._write_lock:
            await self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                await self._conn.rollback()
                raise
            else:
                await self._conn.commit()

    async def current(self) -> AuthorityRecord | None:
        async with self._conn.execute(
            "SELECT revision, authority, actor, at, note FROM backlog_authority "
            "ORDER BY revision DESC LIMIT 1"
        ) as cursor:
            row = await cursor.fetchone()
        return AuthorityRecord.from_row(row) if row is not None else None

    async def append(
        self,
        *,
        authority: BacklogAuthority,
        actor: str,
        note: str,
        at: datetime | None = None,
    ) -> AuthorityRecord:
        moment = at or _utcnow()
        async with self._write() as conn:
            await conn.execute(
                "INSERT INTO backlog_authority (authority, actor, at, note) VALUES (?, ?, ?, ?)",
                (authority.value, actor, moment.isoformat(), note),
            )
            async with conn.execute(
                "SELECT revision, authority, actor, at, note FROM backlog_authority "
                "ORDER BY revision DESC LIMIT 1"
            ) as cursor:
                row = await cursor.fetchone()
        if row is None:  # pragma: no cover - the insert above just created it
            raise RuntimeError("authority append did not persist")
        return AuthorityRecord.from_row(row)

    async def history(self) -> list[AuthorityRecord]:
        async with self._conn.execute(
            "SELECT revision, authority, actor, at, note FROM backlog_authority "
            "ORDER BY revision ASC"
        ) as cursor:
            rows = await cursor.fetchall()
        return [AuthorityRecord.from_row(row) for row in rows]


class SqliteDocumentState:
    """Durable token-stream store for imported documents."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn
        self._write_lock = asyncio.Lock()

    async def ensure_schema(self) -> None:
        # Shared schema script with the ledger; safe to run twice.
        async with serialized_schema_upgrade(self._conn):
            await execute_schema_script(self._conn, _SQLITE_SCHEMA)

    @asynccontextmanager
    async def _write(self) -> AsyncIterator[aiosqlite.Connection]:
        async with self._write_lock:
            await self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                await self._conn.rollback()
                raise
            else:
                await self._conn.commit()

    async def get_tokens(self, document_id: str) -> tuple[tuple[str, str], ...] | None:
        async with self._conn.execute(
            "SELECT tokens FROM backlog_documents WHERE document_id = ?",
            (document_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return tuple((str(kind), str(value)) for kind, value in json.loads(row[0]))

    async def put_tokens(self, document_id: str, tokens: Sequence[tuple[str, str]]) -> None:
        payload = json.dumps([[kind, value] for kind, value in tokens])
        async with self._write() as conn:
            await conn.execute(
                "INSERT INTO backlog_documents (document_id, tokens, updated_at) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(document_id) DO UPDATE SET tokens = excluded.tokens, "
                "updated_at = excluded.updated_at",
                (document_id, payload, _utcnow().isoformat()),
            )


class CutoverError(RuntimeError):
    """The cutover cannot proceed; the message says what is unproven."""


async def import_document(
    store: BacklogStore,
    text: str,
    *,
    document_id: str = ROOT_DOCUMENT_ID,
    workspace_id: str = ROOT_WORKSPACE_ID,
    document_state: DocumentState | None = None,
    actor: str = CUTOVER_ACTOR,
) -> ParsedDocument:
    """Import the Markdown backlog into structured state, stably and idempotently.

    Every item keeps its stable id (``engine-042`` stays ``engine-042``),
    dependencies, verbatim body (acceptance criteria, evidence, prose),
    Markdown status word and open/closed state. Importing an unchanged
    document twice is a no-op: items whose written content matches the stored
    state are left untouched, so re-running the import never churns versions
    or fabricates history. Import never flips authority — the file stays
    canonical until :func:`cutover_to_db` says otherwise.
    """
    document = parse_markdown(text)
    validate_document(document)

    known = set(document.item_ids)
    for index, item in enumerate(document.items):
        item_id = item.item_id
        stored = await store.get_item(item_id)

        dependencies = parse_dependencies(item, known)
        origin = BacklogOrigin(
            document=document_id,
            section=item.section,
            subsection=item.subsection,
            order=index,
            status_word=item.status_word,
            gap_marker=item.gap_marker,
            milestone_text=item.milestone_text,
            header_suffix=item.header_suffix or None,
            body=item.body,
        )
        structured_status = status_to_structured(item.status_word)
        details = "\n".join(item.body)
        if stored is None:
            created = await store.create_item(
                workspace_id=workspace_id,
                title=item.title,
                actor=actor,
                details=details,
                milestone=item.milestone_text,
                source=f"import:{document_id}",
                dependencies=dependencies,
                origin=origin,
                item_id=item_id,
            )
            await _apply_imported_status(store, created, structured_status, actor)
            continue

        changed = (
            stored.title != item.title
            or stored.details != details
            or stored.dependencies != dependencies
            or stored.origin != origin
        )
        if not changed:
            continue
        updated = await store.update_item(
            item_id,
            expected_version=stored.version,
            actor=actor,
            title=item.title,
            details=details,
            dependencies=dependencies,
            origin=origin,
        )
        await _apply_imported_status(store, updated, structured_status, actor)

    if document_state is not None:
        await document_state.put_tokens(document_id, document.tokens)
    return document


async def _apply_imported_status(
    store: BacklogStore,
    item: BacklogItem,
    structured_status: str,
    actor: str,
) -> None:
    """Move an imported item to its written open/closed state, with evidence.

    Terminal written statuses carry closure evidence: the document itself (the
    authoritative source being migrated) is the first evidence reference, and
    the summary records that the closure arrived by import, so the digitized
    backlog is honest about which closures arrived from prose rather than a
    reviewed evidence record.
    """
    if status_is_terminal(structured_status):
        await store.close_item(
            item.item_id,
            expected_version=item.version,
            actor=actor,
            outcome=structured_status,
            closure_summary=f"Imported from a written item in {ROOT_DOCUMENT_ID}",
            evidence_refs=(f"{ROOT_DOCUMENT_ID}#{item.item_id}",),
        )
        return
    if status_is_terminal(item.status):
        await store.reopen_item(
            item.item_id,
            expected_version=item.version,
            actor=actor,
        )
    elif item.status != structured_status:
        await store.update_item(
            item.item_id,
            expected_version=item.version,
            actor=actor,
            status=structured_status,
        )


async def export_document(
    store: BacklogStore,
    document: ParsedDocument,
) -> str:
    """Render the authoritative Markdown from the imported item state.

    Deterministic and reviewable: the furniture replays verbatim, each item
    renders from its stored structured state through the same grammar it was
    written in, and nothing time- or locale-dependent enters the output. This
    is the function the cutover proves byte-identical before flipping
    authority.
    """
    items = await _fetch_items(store, document.item_ids)
    return render_document(document.tokens, items)


def _post_cutover_ids(items: Iterable[BacklogItem], known: set[str]) -> list[str]:
    """Database-created items the token stream cannot know about, in id order.

    Items created in the database after the cutover carry no origin marker
    back into the file: they are appended under the generated heading exactly
    once, in item-id order, so the generated file stays deterministic.
    """
    return sorted(
        item.item_id for item in items if item.item_id not in known and item.origin is None
    )


def _with_appended(replay: list[tuple[str, str]], extra: Sequence[str]) -> list[tuple[str, str]]:
    """Append DB-created item tokens, inserting the generated heading once."""
    if extra and not any(
        kind == FURNITURE and value.strip() == POST_CUTOVER_HEADING for kind, value in replay
    ):
        replay.extend(((FURNITURE, ""), (FURNITURE, POST_CUTOVER_HEADING), (FURNITURE, "")))
    replay.extend((ITEM, item_id) for item_id in extra)
    return replay


async def export_authoritative(
    store: BacklogStore,
    document_state: DocumentState,
    *,
    document_id: str = ROOT_DOCUMENT_ID,
) -> str:
    """Generate the Markdown file from the database alone (post-cutover path).

    The persisted token stream replays furniture verbatim; items come from
    the store in their recorded positions, with database-created items
    appended under a generated heading (once, in item-id order) — the
    determinism the cutover acceptance is tested against.
    """
    tokens = await document_state.get_tokens(document_id)
    if tokens is None:
        raise CutoverError(
            f"cannot generate {document_id}: it has never been imported into the database"
        )
    known = {value for kind, value in tokens if kind == ITEM}
    stored = await store.list_items(ROOT_WORKSPACE_ID)
    replay = _with_appended(list(tokens), _post_cutover_ids(stored, known))
    items = await _fetch_items(store, [value for kind, value in replay if kind == ITEM])
    return render_document(replay, items)


async def _fetch_items(store: BacklogStore, item_ids: Sequence[str]) -> dict[str, BacklogItem]:
    items: dict[str, BacklogItem] = {}
    for item_id in item_ids:
        stored = await store.get_item(item_id)
        if stored is None:
            raise CutoverError(
                f"cannot export {item_id}: the database does not hold the imported item"
            )
        items[item_id] = stored
    return items


async def cutover_to_db(
    store: BacklogStore,
    text: str,
    ledger: AuthorityLedger,
    *,
    actor: str = CUTOVER_ACTOR,
    note: str = "",
    document_id: str = ROOT_DOCUMENT_ID,
    document_state: DocumentState | None = None,
) -> AuthorityRecord:
    """Flip authority to the database — but only once the replacement is proven.

    The proof is the round-trip: import the current file, export the imported
    state, and require byte equality with the original. If the database
    cannot reproduce the document it is not ready to be its authority, and
    the flip is refused with the file still canonical. The flip itself is one
    appended ledger revision — recorded, attributable, and reversible by
    appending a ``markdown`` revision.
    """
    document = await import_document(
        store,
        text,
        document_id=document_id,
        document_state=document_state,
        actor=actor,
    )
    exported = await export_document(store, document)
    if exported != text:
        raise CutoverError(
            "cutover refused: the database export does not reproduce "
            f"{document_id} byte-for-byte; the migration is not lossless yet"
        )
    return await ledger.append(
        authority=BacklogAuthority.DB,
        actor=actor,
        note=note or f"authority cutover: {document_id} is now generated from the database",
    )


async def revert_to_markdown(
    ledger: AuthorityLedger,
    *,
    actor: str,
    note: str = "",
) -> AuthorityRecord:
    """Return authority to the Markdown file during migration validation.

    Reversibility is the safety property that makes the cutover legitimate to
    perform while it is being validated: authority is a ledger decision, so
    reverting is one appended revision — the cutover's history stays intact —
    and the file is canonical again immediately.
    """
    return await ledger.append(
        authority=BacklogAuthority.MARKDOWN,
        actor=actor,
        note=note or "authority reverted to the Markdown backlog during migration validation",
    )


async def current_authority(ledger: AuthorityLedger) -> BacklogAuthority:
    """The authority in force; Markdown until the first cutover revision."""
    record = await ledger.current()
    return record.authority if record is not None else BacklogAuthority.MARKDOWN


def is_written_terminal(item: BacklogItem) -> bool:
    """Whether the item's written Markdown status is a closed status.

    Uses the same effective-word rule as rendering: an imported item whose
    structured status has moved since import reads as its current state, not
    its pre-import word.
    """
    return item.origin is not None and is_terminal_word(effective_status_word(item))


__all__ = [
    "CUTOVER_ACTOR",
    "ROOT_DOCUMENT_ID",
    "ROOT_WORKSPACE_ID",
    "AuthorityLedger",
    "AuthorityRecord",
    "BacklogAuthority",
    "CutoverError",
    "DocumentState",
    "InMemoryAuthorityLedger",
    "InMemoryDocumentState",
    "SqliteAuthorityLedger",
    "SqliteDocumentState",
    "current_authority",
    "cutover_to_db",
    "export_authoritative",
    "export_document",
    "import_document",
    "is_written_terminal",
    "revert_to_markdown",
]
