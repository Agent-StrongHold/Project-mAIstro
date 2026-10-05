"""PostgreSQL system of record for the user model (#1047, ADR-092526-4391).

PostgreSQL is the system of record (ADR-082226-5104 §§1, 5, 6): a fact written
here survives restart, backup and restore, keyed to the canonical user id, and
Ladybug may only cache a projection of it. Two tables:

- ``user_model_facts`` -- one row per ``UserModelFact`` revision. Tombstoning a
  lineage deletes its content revisions and keeps a single tombstone revision,
  so a deleted fact's statement is gone from the record while its lineage
  identity (and therefore its tombstone) survives.
- ``user_model_statement_keys`` -- owner-bound statement key to lineage id,
  appended on every revision. These rows outlive the revisions they pointed at
  on purpose: they are what keeps a tombstone blocking every wording the
  lineage ever held, including one a stale Ladybug working graph replays.

The store implements the same :class:`~maistro.protocols.memory.UserModelStore`
protocol as :class:`~maistro.memory.user_model.store.InMemoryUserModelStore`;
``tests`` conformance runs both against the same cases.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, delete, func, select, update
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from maistro.memory.store import Base
from maistro.memory.user_model.store import _check_follows
from maistro.memory.user_model.types import (
    Correction,
    EvidenceRef,
    FactSensitivity,
    FactState,
    RevisionConflictError,
    TombstonedLineageError,
    UserModelFact,
    fact_key,
    new_fact_id,
)

TOMBSTONE_STATE = FactState.TOMBSTONED.value


def _encode_evidence(evidence: tuple[EvidenceRef, ...]) -> list[dict[str, str]]:
    return [dataclasses.asdict(ref) for ref in evidence]


def _decode_evidence(raw: list[dict[str, str]] | None) -> tuple[EvidenceRef, ...]:
    return tuple(EvidenceRef(**item) for item in (raw or []))


def _encode_correction(correction: Correction | None) -> dict[str, str] | None:
    if correction is None:
        return None
    return {
        "corrected_by": correction.corrected_by,
        "reason": correction.reason,
        "corrected_at": correction.corrected_at.isoformat(),
    }


def _decode_correction(raw: dict[str, str] | None) -> Correction | None:
    if raw is None:
        return None
    return Correction(
        corrected_by=raw["corrected_by"],
        reason=raw["reason"],
        corrected_at=datetime.fromisoformat(raw["corrected_at"]),
    )


class UserModelFactRow(Base):
    """One revision of one user-model fact (append-only until tombstoned)."""

    __tablename__ = "user_model_facts"

    fact_id: Mapped[str] = mapped_column(primary_key=True)
    lineage_id: Mapped[str] = mapped_column(index=True)
    revision: Mapped[int]
    supersedes: Mapped[str | None]
    owner_user_id: Mapped[str] = mapped_column(index=True)
    kind: Mapped[str]
    statement: Mapped[str]
    evidence: Mapped[list[dict[str, str]]] = mapped_column(JSONB)
    first_observed: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_observed: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_reinforced: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confidence: Mapped[float]
    state: Mapped[str]
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sensitivity: Mapped[str]
    reusable: Mapped[bool]
    correction: Mapped[dict[str, str] | None] = mapped_column(JSONB, nullable=True)
    persona_hints: Mapped[list[str]] = mapped_column(JSONB)


class UserModelStatementKeyRow(Base):
    """Statement key to lineage id; retained so tombstones keep blocking."""

    __tablename__ = "user_model_statement_keys"

    fact_key: Mapped[str] = mapped_column(primary_key=True)
    lineage_id: Mapped[str] = mapped_column(index=True)
    owner_user_id: Mapped[str] = mapped_column(index=True)


class PostgresUserModelStore:
    """Durable ``UserModelStore`` twin backed by the shared async engine."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession] | None = None) -> None:
        self._factory = session_factory

    def _sessions(self) -> async_sessionmaker[AsyncSession]:
        if self._factory is not None:
            return self._factory
        from maistro.memory.store import get_async_session_factory

        factory = get_async_session_factory()
        if factory is None:
            raise RuntimeError("No database configured")
        return factory

    @staticmethod
    def _to_fact(row: UserModelFactRow) -> UserModelFact:
        return UserModelFact(
            lineage_id=row.lineage_id,
            revision=row.revision,
            supersedes=row.supersedes,
            owner_user_id=row.owner_user_id,
            kind=row.kind,
            statement=row.statement,
            fact_id=row.fact_id,
            evidence=_decode_evidence(row.evidence),
            first_observed=row.first_observed,
            last_observed=row.last_observed,
            last_reinforced=row.last_reinforced,
            confidence=row.confidence,
            state=FactState(row.state),
            valid_from=row.valid_from,
            valid_until=row.valid_until,
            sensitivity=FactSensitivity(row.sensitivity),
            reusable=row.reusable,
            correction=_decode_correction(row.correction),
            persona_hints=tuple(row.persona_hints or ()),
        )

    @classmethod
    def _columns(cls, fact: UserModelFact) -> dict[str, Any]:
        return {
            "fact_id": fact.fact_id,
            "lineage_id": fact.lineage_id,
            "revision": fact.revision,
            "supersedes": fact.supersedes,
            "owner_user_id": fact.owner_user_id,
            "kind": fact.kind,
            "statement": fact.statement,
            "evidence": _encode_evidence(fact.evidence),
            "first_observed": fact.first_observed,
            "last_observed": fact.last_observed,
            "last_reinforced": fact.last_reinforced,
            "confidence": fact.confidence,
            "state": fact.state.value,
            "valid_from": fact.valid_from,
            "valid_until": fact.valid_until,
            "sensitivity": fact.sensitivity.value,
            "reusable": fact.reusable,
            "correction": _encode_correction(fact.correction),
            "persona_hints": list(fact.persona_hints),
        }

    async def append_revision(self, fact: UserModelFact) -> UserModelFact:
        """Append the next revision in one serialized transaction."""
        async with self._sessions()() as session, session.begin():
            key = fact_key(fact.owner_user_id, fact.statement)
            if await self._lineage_tombstoned(session, fact.lineage_id):
                raise TombstonedLineageError(fact.lineage_id)
            claimed = await session.get(UserModelStatementKeyRow, key)
            if claimed is not None:
                # A tombstone keeps its key rows, so the wording it deleted is
                # refused here even though its content revisions are gone.
                if await self._lineage_tombstoned(session, claimed.lineage_id):
                    raise TombstonedLineageError(fact.lineage_id)
                if claimed.lineage_id != fact.lineage_id:
                    raise RevisionConflictError("statement already belongs to another lineage")
            rows = (
                await session.scalars(
                    select(UserModelFactRow)
                    .where(UserModelFactRow.lineage_id == fact.lineage_id)
                    .order_by(UserModelFactRow.revision)
                    .with_for_update()
                )
            ).all()
            history = [self._to_fact(row) for row in rows]
            _check_follows(history[-1] if history else None, fact)
            if history:
                await session.execute(
                    update(UserModelFactRow)
                    .where(UserModelFactRow.fact_id == history[-1].fact_id)
                    .values(state=FactState.SUPERSEDED.value)
                )
            session.add(UserModelFactRow(**self._columns(fact)))
            if fact.statement.strip():
                # Idempotent: reinforcing the same statement re-derives its key.
                await session.execute(
                    insert(UserModelStatementKeyRow)
                    .values(
                        fact_key=key,
                        lineage_id=fact.lineage_id,
                        owner_user_id=fact.owner_user_id,
                    )
                    .on_conflict_do_nothing(index_elements=["fact_key"])
                )
        return fact

    @staticmethod
    async def _lineage_tombstoned(session: AsyncSession, lineage_id: str) -> bool:
        found = await session.scalar(
            select(UserModelFactRow.fact_id)
            .where(
                UserModelFactRow.lineage_id == lineage_id,
                UserModelFactRow.state == TOMBSTONE_STATE,
            )
            .limit(1)
        )
        return found is not None

    async def _resolve_lineage(self, session: AsyncSession, ref: str) -> str:
        claimed = await session.get(UserModelStatementKeyRow, ref)
        return claimed.lineage_id if claimed is not None else ref

    async def current(self, lineage_or_fact_key: str) -> UserModelFact | None:
        async with self._sessions()() as session:
            lineage_id = await self._resolve_lineage(session, lineage_or_fact_key)
            row = await session.scalar(
                select(UserModelFactRow)
                .where(UserModelFactRow.lineage_id == lineage_id)
                .order_by(UserModelFactRow.revision.desc())
                .limit(1)
            )
            return self._to_fact(row) if row is not None else None

    async def history(self, lineage_id: str) -> list[UserModelFact]:
        async with self._sessions()() as session:
            rows = (
                await session.scalars(
                    select(UserModelFactRow)
                    .where(UserModelFactRow.lineage_id == lineage_id)
                    .order_by(UserModelFactRow.revision)
                )
            ).all()
            return [self._to_fact(row) for row in rows]

    async def list_for_user(self, owner_user_id: str) -> list[UserModelFact]:
        """Latest revision per live lineage of one owner; nobody else's."""
        if not owner_user_id:
            return []
        async with self._sessions()() as session:
            maxima = (
                select(
                    UserModelFactRow.lineage_id,
                    func.max(UserModelFactRow.revision).label("revision"),
                )
                .where(UserModelFactRow.owner_user_id == owner_user_id)
                .group_by(UserModelFactRow.lineage_id)
                .subquery()
            )
            rows = (
                await session.scalars(
                    select(UserModelFactRow).join(
                        maxima,
                        (UserModelFactRow.lineage_id == maxima.c.lineage_id)
                        & (UserModelFactRow.revision == maxima.c.revision),
                    )
                )
            ).all()
            return [self._to_fact(row) for row in rows if row.state != TOMBSTONE_STATE]

    async def tombstone(
        self, lineage_id: str, *, acting_user_id: str, reason: str
    ) -> UserModelFact:
        """Purge the lineage's content and keep who deleted it and why."""
        async with self._sessions()() as session, session.begin():
            rows = (
                await session.scalars(
                    select(UserModelFactRow)
                    .where(UserModelFactRow.lineage_id == lineage_id)
                    .order_by(UserModelFactRow.revision)
                    .with_for_update()
                )
            ).all()
            history = [self._to_fact(row) for row in rows]
            head = history[-1] if history else None
            if head is None or not acting_user_id or head.owner_user_id != acting_user_id:
                raise KeyError(lineage_id)
            if await self._lineage_tombstoned(session, lineage_id):
                return head
            tomb = UserModelFactRow(
                **self._columns(
                    dataclasses.replace(
                        head,
                        fact_id=new_fact_id(),
                        revision=head.revision + 1,
                        supersedes=head.fact_id,
                        statement="",
                        evidence=(),
                        persona_hints=(),
                        state=FactState.TOMBSTONED,
                        correction=Correction(corrected_by=acting_user_id, reason=reason),
                    )
                )
            )
            # Content is deleted, not superseded in place: a forgotten fact's
            # statement must not remain readable in the system of record. The
            # statement-key rows survive so every old wording stays blocked.
            await session.execute(
                delete(UserModelFactRow).where(UserModelFactRow.lineage_id == lineage_id)
            )
            session.add(tomb)
        return await self.current(lineage_id)  # type: ignore[return-value]

    async def is_tombstoned(self, lineage_or_fact_key: str) -> bool:
        """Whether the lineage (by id or any statement key it held) was tombstoned."""
        async with self._sessions()() as session:
            lineage_id = await self._resolve_lineage(session, lineage_or_fact_key)
            return await self._lineage_tombstoned(session, lineage_id)
