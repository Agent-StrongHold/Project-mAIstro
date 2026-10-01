#!/usr/bin/env python3
"""Import, export, and explicitly cut the backlog's authority over (#102).

The one operator entry point for the M3-C5 cutover:

- `import`    — load BACKLOG.md into the database (stable ids, dependencies,
                verbatim bodies, open/closed state). Idempotent; never flips
                authority. Safe to run repeatedly while validating.
- `cutover`   — prove the replacement path (import, export, byte-compare with
                the file), append the `db` authority revision to the durable
                ledger, regenerate the file from the database, and record the
                projection in `quality/backlog-authority.json`. Refuses to
                flip if the round-trip is not byte-exact.
- `generate`  — regenerate BACKLOG.md from the database (db authority only)
                and refresh the recorded export digest.
- `revert`    — append a `markdown` authority revision and restore the file
                to hand-maintained form (banner stripped). The cutover's
                history stays in the ledger.
- `status`    — current authority, ledger history, marker contents.

The database is selected by `--db`: a SQLite file path, or a PostgreSQL DSN in
any spelling the deployment's `database_url` accepts (`postgresql://`,
`postgres://`, `postgresql+asyncpg://`, `postgresql+psycopg://`). The
PostgreSQL path runs the same module API against `PgBacklogStore`,
`PgAuthorityLedger`, and `PgDocumentState` over the Alembic-migrated control
tables (`048`/`049`); a database they have not touched is refused with a
pointer to `alembic upgrade head`.

Run: `uv run python scripts/backlog_cutover.py --db .backlog.sqlite3 status`
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "maistro-core" / "src"))

import aiosqlite  # noqa: E402

from maistro.backlog.cutover import (  # noqa: E402
    ROOT_DOCUMENT_ID,
    AuthorityLedger,
    BacklogAuthority,
    DocumentState,
    SqliteAuthorityLedger,
    SqliteDocumentState,
    current_authority,
    cutover_to_db,
    export_authoritative,
    import_document,
    revert_to_markdown,
)
from maistro.backlog.sqlite_store import SqliteBacklogStore  # noqa: E402
from maistro.backlog.store import BacklogStore  # noqa: E402

BACKLOG = ROOT / "BACKLOG.md"
MARKER = ROOT / "quality" / "backlog-authority.json"

GENERATED_BANNER = (
    "<!-- GENERATED from the backlog database (authority revision {revision}). "
    "Direct edits are not authoritative; regenerate with "
    "`scripts/backlog_cutover.py generate` or revert with `revert`. -->"
)


class _Opened:
    """The control-store triple plus the close for whatever connection opened
    them — an aiosqlite connection or an asyncpg pool."""

    def __init__(
        self,
        store: BacklogStore,
        ledger: AuthorityLedger,
        documents: DocumentState,
        closer: Callable[[], Awaitable[None]],
    ) -> None:
        self.store = store
        self.ledger = ledger
        self.documents = documents
        self._closer = closer

    async def close(self) -> None:
        await self._closer()


def _read_marker() -> dict[str, object]:
    if not MARKER.exists():
        return {"authority": "markdown", "revision": 0}
    return json.loads(MARKER.read_text())


def _write_marker(**updates: object) -> None:
    marker = _read_marker()
    marker.update(updates)
    with MARKER.open("w") as handle:
        json.dump(marker, handle, indent=1, ensure_ascii=False)
        handle.write("\n")


def _write_generated(text: str, revision: int) -> str:
    content = GENERATED_BANNER.format(revision=revision) + "\n" + text
    BACKLOG.write_text(content)
    return content


async def _open_sqlite(db_path: str) -> _Opened:
    conn = await aiosqlite.connect(db_path)
    store = SqliteBacklogStore(conn)
    ledger = SqliteAuthorityLedger(conn)
    documents = SqliteDocumentState(conn)
    await store.ensure_schema()
    await ledger.ensure_schema()
    await documents.ensure_schema()
    return _Opened(store, ledger, documents, conn.close)


def _asyncpg_dsn(database_url: str) -> str:
    """Normalize the SQLAlchemy-shaped spellings to one asyncpg accepts."""
    scheme, _, rest = database_url.partition("://")
    if scheme in ("postgresql", "postgres"):
        return database_url
    return f"postgresql://{rest}"


async def _open_postgres(database_url: str) -> _Opened:
    import asyncpg  # deferred: the SQLite default needs no driver

    from maistro.backlog.pg_store import (
        PgAuthorityLedger,
        PgBacklogStore,
        PgDocumentState,
    )

    pool = await asyncpg.create_pool(_asyncpg_dsn(database_url))
    store = PgBacklogStore(pool)
    ledger = PgAuthorityLedger(pool)
    documents = PgDocumentState(pool)
    try:
        await ledger.ensure_schema()
        await documents.ensure_schema()
    except BaseException:
        await pool.close()
        raise
    return _Opened(store, ledger, documents, pool.close)


#: In step with `maistro.container.POSTGRES_SCHEMES`, which a script cannot
#: import for free (it drags in the whole container). Any new scheme there
#: must be mirrored here or that deployment's cutover lands on SQLite.
_POSTGRES_SCHEMES = (
    "postgresql://",
    "postgres://",
    "postgresql+asyncpg://",
    "postgresql+psycopg://",
)


async def _open(database: str) -> _Opened:
    if database.startswith(_POSTGRES_SCHEMES):
        return await _open_postgres(database)
    return await _open_sqlite(database)


async def cmd_status(args: argparse.Namespace) -> int:
    opened = await _open(args.db)
    try:
        authority = await current_authority(opened.ledger)
        marker = _read_marker()
        tokens = await opened.documents.get_tokens(ROOT_DOCUMENT_ID)
        print(f"authority: {authority.value}")
        print(f"marker:    {json.dumps(marker)}")
        print(
            f"document:  {ROOT_DOCUMENT_ID} "
            f"({'imported' if tokens is not None else 'never imported'})"
        )
        for record in await opened.ledger.history():
            print(
                f"  revision {record.revision}: {record.authority.value} "
                f"by {record.actor} at {record.at.isoformat()} — {record.note}"
            )
    finally:
        await opened.close()
    return 0


async def cmd_import(args: argparse.Namespace) -> int:
    text = BACKLOG.read_text()
    opened = await _open(args.db)
    try:
        document = await import_document(
            opened.store,
            text,
            document_id=ROOT_DOCUMENT_ID,
            document_state=opened.documents,
        )
        print(f"imported {len(document.items)} items from {ROOT_DOCUMENT_ID} into {args.db}")
        print("authority unchanged: BACKLOG.md stays canonical until `cutover`")
    finally:
        await opened.close()
    return 0


async def cmd_cutover(args: argparse.Namespace) -> int:
    text = BACKLOG.read_text()
    opened = await _open(args.db)
    store, ledger, documents = opened.store, opened.ledger, opened.documents
    try:
        record = await cutover_to_db(
            store,
            text,
            ledger,
            actor=args.actor,
            note=args.note,
            document_id=ROOT_DOCUMENT_ID,
            document_state=documents,
        )
        try:
            generated = _write_generated(
                await export_authoritative(store, documents), record.revision
            )
            _write_marker(
                authority=BacklogAuthority.DB.value,
                revision=record.revision,
                updated_at=datetime.now(UTC).isoformat(),
                export_sha256=hashlib.sha256(generated.encode()).hexdigest(),
            )
        except OSError as exc:
            # Compensating transaction: the durable ledger must not claim db
            # authority while the generated projections were not written (e.g.
            # read-only checkout, disk full). Append a `markdown` revision so
            # the ledger and the files agree that BACKLOG.md stayed canonical.
            await revert_to_markdown(
                ledger,
                actor=args.actor,
                note=f"cutover rolled back: writing generated files failed ({exc})",
            )
            raise
        print(f"cutover recorded: revision {record.revision} — the database is authoritative")
        print(f"{BACKLOG.name} regenerated from the database and its digest recorded")
    finally:
        await opened.close()
    return 0


async def cmd_generate(args: argparse.Namespace) -> int:
    opened = await _open(args.db)
    try:
        ledger = opened.ledger
        authority = await current_authority(ledger)
        if authority is not BacklogAuthority.DB:
            print(
                f"refused: authority is {authority.value}; `generate` writes the generated "
                "file and is meaningful only under db authority",
                file=sys.stderr,
            )
            return 1
        record = await ledger.current()
        revision = record.revision if record is not None else 0
        generated = _write_generated(
            await export_authoritative(opened.store, opened.documents), revision
        )
        _write_marker(
            authority=BacklogAuthority.DB.value,
            revision=revision,
            updated_at=datetime.now(UTC).isoformat(),
            export_sha256=hashlib.sha256(generated.encode()).hexdigest(),
        )
        print(f"{BACKLOG.name} regenerated from the database (authority revision {revision})")
    finally:
        await opened.close()
    return 0


async def cmd_revert(args: argparse.Namespace) -> int:
    opened = await _open(args.db)
    try:
        record = await revert_to_markdown(opened.ledger, actor=args.actor, note=args.note)
        text = BACKLOG.read_text()
        if text.startswith("<!-- GENERATED from the backlog database"):
            _, _, rest = text.partition("\n")
            BACKLOG.write_text(rest)
        _write_marker(
            authority=BacklogAuthority.MARKDOWN.value,
            revision=record.revision,
            updated_at=datetime.now(UTC).isoformat(),
            export_sha256=None,
        )
        print(f"reverted: revision {record.revision} — {BACKLOG.name} is hand-maintained again")
        print("the cutover history remains in the ledger")
    finally:
        await opened.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        default=str(ROOT / ".backlog-cutover.sqlite3"),
        help="backlog database: a SQLite file path or a PostgreSQL DSN",
    )
    # Actor/note are accepted on the root and on the mutating subcommands, so
    # both `--actor x cutover` and `cutover --actor x` work.
    mutating = argparse.ArgumentParser(add_help=False)
    mutating.add_argument("--actor", default="backlog-cutover", help="actor recorded on changes")
    mutating.add_argument("--note", default="", help="note recorded on the authority revision")
    parser.add_argument("--actor", default="backlog-cutover", help="actor recorded on changes")
    parser.add_argument("--note", default="", help="note recorded on the authority revision")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status", help="show the current authority and ledger history")
    sub.add_parser("import", help="import BACKLOG.md into the database (no authority change)")
    sub.add_parser(
        "cutover",
        parents=[mutating],
        help="prove the round-trip, then flip authority to the database",
    )
    sub.add_parser("generate", help="regenerate BACKLOG.md from the database (db authority)")
    sub.add_parser("revert", parents=[mutating], help="return authority to the Markdown file")
    args = parser.parse_args()
    commands = {
        "status": cmd_status,
        "import": cmd_import,
        "cutover": cmd_cutover,
        "generate": cmd_generate,
        "revert": cmd_revert,
    }
    return asyncio.run(commands[args.command](args))


if __name__ == "__main__":
    raise SystemExit(main())
