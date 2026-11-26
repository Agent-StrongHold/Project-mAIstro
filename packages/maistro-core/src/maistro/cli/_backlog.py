"""`maistro backlog` — the shipped entry point for the #102 authority cutover.

One command group for the M3-C5 cutover lifecycle and for the authorized
agent work loop that runs against the same database after it:

- `import`   — load the backlog document into the database (stable ids,
               dependencies, verbatim bodies, open/closed state). Idempotent;
               never flips authority. Safe to run repeatedly while validating.
- `cutover`  — prove the replacement path (import, export, byte-compare with
               the document), append the `db` authority revision to the durable
               ledger, regenerate the document from the database, and record
               the projection in the authority marker. Refuses to flip if the
               round-trip is not byte-exact.
- `generate` — regenerate the document from the database (db authority only)
               and refresh the recorded export digest.
- `revert`   — append a `markdown` authority revision and restore the document
               to hand-maintained form (banner stripped). The cutover's
               history stays in the ledger.
- `status`   — current authority, ledger history, marker contents.
- `items`, `select`, `claim`, `write`, `release` — the authorized
               :class:`~maistro.backlog.agent_surface.AgentBacklogSurface`
               work loop (list/select/claim/write) driven against the same
               database, so an operator — or an agent harness shelling into
               the shipped CLI — exercises exactly the surface a Workspace
               Agent consumes.

The database is selected by `--db`: a SQLite file path, or a PostgreSQL DSN
in any spelling the deployment's `database_url` accepts (`postgresql://`,
`postgres://`, `postgresql+asyncpg://`, `postgresql+psycopg://`). The
PostgreSQL path runs the same module API against `PgBacklogStore`,
`PgAuthorityLedger`, and `PgDocumentState` over the Alembic-migrated control
tables; a database they have not touched is refused with a pointer to
`alembic upgrade head`.

The authority marker defaults to the checkout's `quality/backlog-authority.json`
(resolved from the working directory, or the `MAISTRO_BACKLOG_AUTHORITY_FILE`
override the Conductor service also honors); `--marker` overrides both.

Run: `uv run maistro backlog status --db .backlog.sqlite3`
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import os
from collections.abc import Awaitable, Callable, Coroutine
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal, cast

import typer
from typer import Option, Typer

from maistro.backlog.agent_surface import AgentBacklogSurface, AgentSurfaceError, Authorize
from maistro.backlog.cutover import (
    ROOT_DOCUMENT_ID,
    AuthorityLedger,
    BacklogAuthority,
    CutoverError,
    DocumentState,
    SqliteAuthorityLedger,
    SqliteDocumentState,
    current_authority,
    cutover_to_db,
    export_authoritative,
    import_document,
    revert_to_markdown,
)
from maistro.backlog.markdown_io import MarkdownBacklogError
from maistro.backlog.model import (
    BacklogClaimError,
    BacklogItem,
    BacklogItemNotFound,
    BacklogVersionConflict,
)
from maistro.backlog.sqlite_store import SqliteBacklogStore
from maistro.backlog.store import DEFAULT_LEASE_SECONDS, BacklogStore

app = Typer(help="Backlog authority cutover and the agent work surface (#102).")

#: In step with `maistro.container.POSTGRES_SCHEMES`. Any new scheme there
#: must be mirrored here or that deployment's cutover lands on SQLite.
_POSTGRES_SCHEMES = (
    "postgresql://",
    "postgres://",
    "postgresql+asyncpg://",
    "postgresql+psycopg://",
)

GENERATED_BANNER = (
    "<!-- GENERATED from the backlog database (authority revision {revision}). "
    "Direct edits are not authoritative; regenerate with "
    "`maistro backlog generate` or revert with `maistro backlog revert`. -->"
)

DbOpt = Annotated[str, Option("--db", help="Backlog database: a SQLite path or a PostgreSQL DSN.")]
MarkerOpt = Annotated[
    Path | None,
    Option(
        "--marker",
        help="Authority marker path [default: $MAISTRO_BACKLOG_AUTHORITY_FILE or ./quality/backlog-authority.json].",
    ),
]
DocumentOpt = Annotated[
    Path,
    Option("--document", help="The backlog Markdown document the cutover manages."),
]
ActorOpt = Annotated[str, Option("--actor", help="Actor recorded on changes.")]
NoteOpt = Annotated[str, Option("--note", help="Note recorded on the authority revision.")]
WorkspaceOpt = Annotated[str, Option("--workspace", help="Workspace whose items are in scope.")]


class RoleChoice(StrEnum):
    """The workspace roles an explicit CLI invocation may assert."""

    viewer = "viewer"
    editor = "editor"
    owner = "owner"


RoleOpt = Annotated[
    RoleChoice | None,
    Option(
        "--role",
        help=(
            "Workspace role asserted for the actor (viewer/editor/owner). The CLI is the "
            "authorization point: omit it and every request fails closed."
        ),
    ),
]


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


async def _open_sqlite(db_path: str) -> _Opened:
    import aiosqlite

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


async def _open(database: str) -> _Opened:
    if database.startswith(_POSTGRES_SCHEMES):
        return await _open_postgres(database)
    return await _open_sqlite(database)


def marker_path(explicit: Path | None) -> Path:
    """The authority marker to read and write.

    Precedence: an explicit `--marker`, then `MAISTRO_BACKLOG_AUTHORITY_FILE`
    (the override the Conductor service honors), then the checkout-relative
    `quality/backlog-authority.json` resolved from the working directory.
    """
    if explicit is not None:
        return explicit
    env = os.environ.get("MAISTRO_BACKLOG_AUTHORITY_FILE")
    if env:
        return Path(env)
    return Path("quality") / "backlog-authority.json"


def _read_marker(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"authority": "markdown", "revision": 0}
    loaded: dict[str, object] = json.loads(path.read_text())
    return loaded


def _write_marker(path: Path, **updates: object) -> None:
    marker = _read_marker(path)
    marker.update(updates)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        json.dump(marker, handle, indent=1, ensure_ascii=False)
        handle.write("\n")


def _write_generated(document: Path, text: str, revision: int) -> str:
    content = GENERATED_BANNER.format(revision=revision) + "\n" + text
    document.write_text(content)
    return content


def _run(coro: Coroutine[Any, Any, int]) -> int:
    return asyncio.run(coro)


def _refuses(fn: Callable[..., int]) -> Callable[..., int]:
    """Translate domain refusals into exit code 1 with the reason on stderr.

    A refused cutover, an unauthorized agent verb and a version conflict are
    answers, not crashes: the operator (or the agent harness shelling into
    this CLI) gets the reason and a failure exit code, never a traceback.
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> int:
        try:
            return fn(*args, **kwargs)
        except (
            AgentSurfaceError,
            BacklogClaimError,
            BacklogItemNotFound,
            BacklogVersionConflict,
            CutoverError,
            MarkdownBacklogError,
        ) as exc:
            typer.echo(f"error: {exc}", err=True)
            raise typer.Exit(code=1) from exc

    return wrapper


def _static_role(role: str | None) -> Authorize:
    """The CLI's authorization callback: the operator asserts one role.

    The surface requires an authorization decision from its embedder and
    refuses to make tenancy decisions itself. A human (or an agent harness)
    invoking the shipped CLI declares the actor's workspace role explicitly;
    omitting it yields ``None`` — no relationship — so every request fails
    closed with not-found semantics. ``role`` arrives from :class:`RoleChoice`,
    whose values are exactly the surface's role literals.
    """

    async def authorize(
        actor: str, workspace_id: str, action: str
    ) -> Literal["viewer", "editor", "owner"] | None:
        return cast("Literal['viewer', 'editor', 'owner'] | None", role)

    return authorize


async def _open_agent_surface(
    database: str, workspace: str, actor: str, role: str | None
) -> tuple[_Opened, AgentBacklogSurface]:
    opened = await _open(database)
    surface = AgentBacklogSurface(opened.store, _static_role(role))
    return opened, surface


def _item_json(item: BacklogItem | None) -> str:
    if item is None:
        return "null"
    return json.dumps(item.model_dump(mode="json"), indent=1, sort_keys=True)


# ---------------------------------------------------------------------------
# The cutover lifecycle
# ---------------------------------------------------------------------------


@app.command("status")
@_refuses
def status(db: DbOpt = ".backlog-cutover.sqlite3", marker: MarkerOpt = None) -> int:
    """Show the current authority and ledger history."""

    async def run() -> int:
        opened = await _open(db)
        try:
            authority = await current_authority(opened.ledger)
            recorded = _read_marker(marker_path(marker))
            tokens = await opened.documents.get_tokens(ROOT_DOCUMENT_ID)
            typer.echo(f"authority: {authority.value}")
            typer.echo(f"marker:    {json.dumps(recorded)}")
            typer.echo(
                f"document:  {ROOT_DOCUMENT_ID} "
                f"({'imported' if tokens is not None else 'never imported'})"
            )
            for record in await opened.ledger.history():
                typer.echo(
                    f"  revision {record.revision}: {record.authority.value} "
                    f"by {record.actor} at {record.at.isoformat()} — {record.note}"
                )
        finally:
            await opened.close()
        return 0

    return _run(run())


@app.command("import")
@_refuses
def import_cmd(
    db: DbOpt = ".backlog-cutover.sqlite3",
    document: DocumentOpt = Path("BACKLOG.md"),
) -> int:
    """Import the backlog document into the database (no authority change)."""

    async def run() -> int:
        text = document.read_text()
        opened = await _open(db)
        try:
            parsed = await import_document(
                opened.store,
                text,
                document_id=ROOT_DOCUMENT_ID,
                document_state=opened.documents,
            )
            typer.echo(f"imported {len(parsed.items)} items from {ROOT_DOCUMENT_ID} into {db}")
            typer.echo("authority unchanged: the document stays canonical until `cutover`")
        finally:
            await opened.close()
        return 0

    return _run(run())


@app.command("cutover")
@_refuses
def cutover(
    db: DbOpt = ".backlog-cutover.sqlite3",
    document: DocumentOpt = Path("BACKLOG.md"),
    marker: MarkerOpt = None,
    actor: ActorOpt = "backlog-cutover",
    note: NoteOpt = "",
) -> int:
    """Prove the round-trip, then flip authority to the database."""

    async def run() -> int:
        text = document.read_text()
        opened = await _open(db)
        store, ledger, documents = opened.store, opened.ledger, opened.documents
        try:
            record = await cutover_to_db(
                store,
                text,
                ledger,
                actor=actor,
                note=note,
                document_id=ROOT_DOCUMENT_ID,
                document_state=documents,
            )
            try:
                generated = _write_generated(
                    document, await export_authoritative(store, documents), record.revision
                )
                _write_marker(
                    marker_path(marker),
                    authority=BacklogAuthority.DB.value,
                    revision=record.revision,
                    updated_at=datetime.now(UTC).isoformat(),
                    export_sha256=hashlib.sha256(generated.encode()).hexdigest(),
                )
            except OSError as exc:
                # Compensating transaction: the durable ledger must not claim
                # db authority while the generated projections were not written
                # (e.g. read-only checkout, disk full). Append a `markdown`
                # revision so the ledger and the files agree the document
                # stayed canonical.
                await revert_to_markdown(
                    ledger,
                    actor=actor,
                    note=f"cutover rolled back: writing generated files failed ({exc})",
                )
                raise
            typer.echo(
                f"cutover recorded: revision {record.revision} — the database is authoritative"
            )
            typer.echo(f"{document.name} regenerated from the database and its digest recorded")
        finally:
            await opened.close()
        return 0

    return _run(run())


@app.command("generate")
@_refuses
def generate(
    db: DbOpt = ".backlog-cutover.sqlite3",
    document: DocumentOpt = Path("BACKLOG.md"),
    marker: MarkerOpt = None,
) -> int:
    """Regenerate the backlog document from the database (db authority)."""

    async def run() -> int:
        opened = await _open(db)
        try:
            ledger = opened.ledger
            authority = await current_authority(ledger)
            if authority is not BacklogAuthority.DB:
                typer.echo(
                    f"refused: authority is {authority.value}; `generate` writes the generated "
                    "document and is meaningful only under db authority",
                    err=True,
                )
                raise typer.Exit(code=1)
            record = await ledger.current()
            revision = record.revision if record is not None else 0
            generated = _write_generated(
                document, await export_authoritative(opened.store, opened.documents), revision
            )
            _write_marker(
                marker_path(marker),
                authority=BacklogAuthority.DB.value,
                revision=revision,
                updated_at=datetime.now(UTC).isoformat(),
                export_sha256=hashlib.sha256(generated.encode()).hexdigest(),
            )
            typer.echo(
                f"{document.name} regenerated from the database (authority revision {revision})"
            )
        finally:
            await opened.close()
        return 0

    return _run(run())


@app.command("revert")
@_refuses
def revert(
    db: DbOpt = ".backlog-cutover.sqlite3",
    document: DocumentOpt = Path("BACKLOG.md"),
    marker: MarkerOpt = None,
    actor: ActorOpt = "backlog-cutover",
    note: NoteOpt = "",
) -> int:
    """Return authority to the Markdown document."""

    async def run() -> int:
        opened = await _open(db)
        try:
            record = await revert_to_markdown(opened.ledger, actor=actor, note=note)
            text = document.read_text()
            if text.startswith("<!-- GENERATED from the backlog database"):
                _, _, rest = text.partition("\n")
                document.write_text(rest)
            _write_marker(
                marker_path(marker),
                authority=BacklogAuthority.MARKDOWN.value,
                revision=record.revision,
                updated_at=datetime.now(UTC).isoformat(),
                export_sha256=None,
            )
            typer.echo(
                f"reverted: revision {record.revision} — {document.name} is hand-maintained again"
            )
            typer.echo("the cutover history remains in the ledger")
        finally:
            await opened.close()
        return 0

    return _run(run())


# ---------------------------------------------------------------------------
# The authorized agent work loop (same database, fail-closed surface)
# ---------------------------------------------------------------------------


@app.command("items")
@_refuses
def items(
    workspace: WorkspaceOpt,
    db: DbOpt = ".backlog-cutover.sqlite3",
    actor: ActorOpt = "backlog-agent",
    role: RoleOpt = None,
    work_status: Annotated[
        str | None,
        Option("--status", help="Filter by item status before the surface applies its rules."),
    ] = None,
) -> int:
    """List the open items the actor may see in the workspace."""

    async def run() -> int:
        opened, surface = await _open_agent_surface(db, workspace, actor, role)
        try:
            found = await surface.list_items(
                actor=actor, workspace_id=workspace, status=work_status
            )
            typer.echo(
                json.dumps([i.model_dump(mode="json") for i in found], indent=1, sort_keys=True)
            )
        finally:
            await opened.close()
        return 0

    return _run(run())


@app.command("select")
@_refuses
def select(
    workspace: WorkspaceOpt,
    db: DbOpt = ".backlog-cutover.sqlite3",
    actor: ActorOpt = "backlog-agent",
    role: RoleOpt = None,
) -> int:
    """The highest-priority claimable item for the actor, or 'none'."""

    async def run() -> int:
        opened, surface = await _open_agent_surface(db, workspace, actor, role)
        try:
            selection = await surface.select(actor=actor, workspace_id=workspace)
        finally:
            await opened.close()
        if selection is None:
            typer.echo(f"no claimable item for {actor!r} in {workspace!r}")
            return 0
        typer.echo(
            json.dumps(
                {"reason": selection.reason, "item": selection.item.model_dump(mode="json")},
                indent=1,
                sort_keys=True,
            )
        )
        return 0

    return _run(run())


@app.command("claim")
@_refuses
def claim(
    item_id: Annotated[str, typer.Argument(help="The backlog item to lease.")],
    workspace: WorkspaceOpt,
    db: DbOpt = ".backlog-cutover.sqlite3",
    actor: ActorOpt = "backlog-agent",
    role: RoleOpt = None,
    lease_seconds: Annotated[
        float, Option("--lease-seconds", help="Lease duration in seconds.")
    ] = DEFAULT_LEASE_SECONDS,
) -> int:
    """Lease the right to progress one item."""

    async def run() -> int:
        opened, surface = await _open_agent_surface(db, workspace, actor, role)
        try:
            held = await surface.claim(item_id, actor=actor, lease_seconds=lease_seconds)
            typer.echo(json.dumps(held.model_dump(mode="json"), indent=1, sort_keys=True))
        finally:
            await opened.close()
        return 0

    return _run(run())


@app.command("write")
@_refuses
def write(
    item_id: Annotated[str, typer.Argument(help="The backlog item to edit.")],
    workspace: WorkspaceOpt,
    expected_version: Annotated[
        int, Option("--expected-version", help="The version this edit was prepared against.")
    ],
    db: DbOpt = ".backlog-cutover.sqlite3",
    actor: ActorOpt = "backlog-agent",
    role: RoleOpt = None,
    claim_id: Annotated[
        str | None,
        Option("--claim-id", help="The actor's live claim on the item, when one exists."),
    ] = None,
    title: Annotated[str | None, Option("--title")] = None,
    details: Annotated[str | None, Option("--details")] = None,
    new_status: Annotated[str | None, Option("--status")] = None,
    priority: Annotated[int | None, Option("--priority")] = None,
) -> int:
    """An attributed edit; a live claim must belong to the writer.

    The four editable fields are passed through as given: an option left at
    its default ``None`` means "no change" to the store, exactly like
    omitting it.
    """

    async def run() -> int:
        opened, surface = await _open_agent_surface(db, workspace, actor, role)
        try:
            updated = await surface.write(
                item_id,
                actor=actor,
                expected_version=expected_version,
                claim_id=claim_id,
                title=title,
                details=details,
                status=new_status,
                priority=priority,
            )
            typer.echo(_item_json(updated))
        finally:
            await opened.close()
        return 0

    return _run(run())


@app.command("release")
@_refuses
def release(
    item_id: Annotated[str, typer.Argument(help="The leased backlog item.")],
    claim_id: Annotated[str, Option("--claim-id", help="The claim to release.")],
    workspace: WorkspaceOpt,
    db: DbOpt = ".backlog-cutover.sqlite3",
    actor: ActorOpt = "backlog-agent",
    role: RoleOpt = None,
) -> int:
    """Release the actor's own lease."""

    async def run() -> int:
        opened, surface = await _open_agent_surface(db, workspace, actor, role)
        try:
            await surface.release(item_id, actor=actor, claim_id=claim_id)
            typer.echo(f"released {claim_id} on {item_id}")
        finally:
            await opened.close()
        return 0

    return _run(run())
