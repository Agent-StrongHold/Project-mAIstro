"""SQLite-backed learning store (homelab/single-instance deployments)."""

from __future__ import annotations

import itertools
import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from maistro.memory.learnings.evidence import (
    DEFAULT_MIN_PROMOTION_CONFIDENCE,
    merge_applicability,
    promotion_blockers,
)
from maistro.memory.learnings.lifecycle import (
    InvalidStageTransition,
    StageTransition,
    plan_advance,
)
from maistro.observability.correlation import ExecutionProvenance, observed_provenance
from maistro.persistence.learning_contract import (
    LEARNING_GENERATED_FIELDS,
    LEARNING_PERSISTED_FIELDS,
)
from maistro.persistence.learning_scope import learning_scope_predicate
from maistro.sqlite_schema import serialized_schema_upgrade
from maistro.types.memory import (
    DEFAULT_LEARNING_CONFIDENCE,
    EPISTEMIC_BONUS,
    EpistemicType,
    Learning,
    LearningStage,
    MemoryScope,
)

if TYPE_CHECKING:
    import aiosqlite

_SCHEMA = """
CREATE TABLE IF NOT EXISTS learnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL DEFAULT 'general',
    trigger_keys TEXT NOT NULL DEFAULT '[]',
    learning TEXT NOT NULL DEFAULT '',
    tool_name TEXT NOT NULL DEFAULT '',
    source_query TEXT NOT NULL DEFAULT '',
    agent_id TEXT NOT NULL DEFAULT '',
    user_id TEXT,
    org_id TEXT NOT NULL DEFAULT '',
    team_id TEXT NOT NULL DEFAULT '',
    scope TEXT NOT NULL DEFAULT 'agent',
    hit_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    rca_category TEXT,
    rca_prevention TEXT NOT NULL DEFAULT '',
    success_after_use INTEGER NOT NULL DEFAULT 0,
    failure_after_use INTEGER NOT NULL DEFAULT 0,
    run_id TEXT,
    node_run_id TEXT,
    attempt_id TEXT,
    epistemic_type TEXT NOT NULL DEFAULT 'empirical',
    works_when TEXT NOT NULL DEFAULT '[]',
    avoid_in TEXT NOT NULL DEFAULT '[]',
    confidence REAL,
    evidence_run_ids TEXT NOT NULL DEFAULT '[]',
    evaluation_ids TEXT NOT NULL DEFAULT '[]',
    applicability TEXT NOT NULL DEFAULT '{}',
    reinforcement_count INTEGER NOT NULL DEFAULT 0,
    contradiction_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT,
    last_confirmed_at TEXT,
    stage TEXT NOT NULL DEFAULT 'memory',
    validated_by TEXT NOT NULL DEFAULT '',
    validated_at TEXT,
    supersedes INTEGER,
    superseded_by INTEGER,
    promoted_by TEXT NOT NULL DEFAULT ''
)
"""

#: Append-only ladder audit trail (ADR-103). One row per accepted transition;
#: nothing ever updates or deletes from it. `org_id` is copied from the row at
#: transition time so the audit read can scope exactly like every other read.
_STAGE_HISTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS learning_stage_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    learning_id INTEGER NOT NULL,
    org_id TEXT NOT NULL DEFAULT '',
    from_stage TEXT NOT NULL,
    to_stage TEXT NOT NULL,
    actor TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
)
"""

#: One module-level DDL table for every column an older file may lack, in the
#: order the in-place upgrade adds them. One literal rather than several named
#: collections because the retention-reference inventory's AST scan resolves a
#: formatted `ALTER TABLE` only from a loop over a module-level dict literal
#: (`.items()` shape) — an f-string whose parts it cannot resolve statically
#: fails the suite rather than being assumed run_id-free. The commented groups
#: keep the history each collection used to carry.
_UPGRADE_COLUMNS = {
    # Legacy scope columns (pre-team/source_query files), no default: existing
    # rows have unknown scope and must not be silently fabricated.
    "source_query": "TEXT",
    "team_id": "TEXT",
    # Producer columns (#709), nullable for the same reason migration 026 makes
    # them nullable in PostgreSQL: a row written with no execution in scope
    # names none, and '' would name a Run whose id is empty.
    "run_id": "TEXT",
    "node_run_id": "TEXT",
    "attempt_id": "TEXT",
    # Applicability, confidence and epistemic columns (M4-B3 + the pipeline
    # epistemics ADR-100126-8c2d). Defaults mirror the dataclass: a pre-epistemics
    # row lands as the local empirical learning it implicitly was. `confidence`
    # alone stays nullable: an unmeasured row is stored as NULL, and the decode
    # maps a legacy NULL to the default — it must never read back as measured,
    # and promotion blocks it at the floor either way.
    "epistemic_type": "TEXT NOT NULL DEFAULT 'empirical'",
    "works_when": "TEXT NOT NULL DEFAULT '[]'",
    "avoid_in": "TEXT NOT NULL DEFAULT '[]'",
    "confidence": "REAL",
    "evidence_run_ids": "TEXT NOT NULL DEFAULT '[]'",
    "evaluation_ids": "TEXT NOT NULL DEFAULT '[]'",
    "applicability": "TEXT NOT NULL DEFAULT '{}'",
    "reinforcement_count": "INTEGER NOT NULL DEFAULT 0",
    "contradiction_count": "INTEGER NOT NULL DEFAULT 0",
    "created_at": "TEXT",
    "last_confirmed_at": "TEXT",
    # M4-B1 (ADR-103): the stage columns default to the bottom rung with blank
    # actors. Pre-ladder rows keep `memory` and never gain a fabricated
    # validation or promotion claim; the ledger starts empty and records only
    # transitions that actually happened.
    "stage": "TEXT NOT NULL DEFAULT 'memory'",
    "validated_by": "TEXT NOT NULL DEFAULT ''",
    "validated_at": "TEXT",
    "supersedes": "INTEGER",
    "superseded_by": "INTEGER",
    "promoted_by": "TEXT NOT NULL DEFAULT ''",
}

# Kept next to the SQL so the conformance test can detect a new Learning field
# that is not represented by both persistence twins.
_SQLITE_PERSISTED_FIELDS = LEARNING_PERSISTED_FIELDS
_SQLITE_GENERATED_FIELDS = LEARNING_GENERATED_FIELDS
_SQLITE_INSERT_FIELDS = (
    "category",
    "trigger_keys",
    "learning",
    "tool_name",
    "source_query",
    "agent_id",
    "user_id",
    "org_id",
    "team_id",
    "scope",
    "hit_count",
    "status",
    "rca_category",
    "rca_prevention",
    "success_after_use",
    "failure_after_use",
    "run_id",
    "node_run_id",
    "attempt_id",
    "epistemic_type",
    "works_when",
    "avoid_in",
    "confidence",
    "evidence_run_ids",
    "evaluation_ids",
    "applicability",
    "reinforcement_count",
    "contradiction_count",
    "created_at",
    "last_confirmed_at",
    "stage",
    "validated_by",
    "validated_at",
    "promoted_by",
    "supersedes",
    "superseded_by",
)


async def _add_missing_columns(
    conn: aiosqlite.Connection,
    columns: set[str],
) -> None:
    """Add every declared upgrade column an older file does not have yet.

    SQLite has no `ADD COLUMN IF NOT EXISTS`, so the `PRAGMA table_info`
    column set is passed in and only the missing columns are added. The DDL
    loop reads `_UPGRADE_COLUMNS` directly — a module-level dict literal — so
    the retention-reference inventory's AST scan can resolve the formatted
    `ALTER TABLE` statement statically.
    """
    for column, column_type in _UPGRADE_COLUMNS.items():
        if column not in columns:
            await conn.execute(f"ALTER TABLE learnings ADD COLUMN {column} {column_type}")


class SqliteLearningStore:
    """SQLite-backed learning store implementing the same protocol as PgLearningStore."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    async def ensure_schema(self) -> None:
        """Create the learnings table, and upgrade one created before its columns.

        `org_id`, `team_id` and `source_query` were in the `Learning` dataclass
        long before the SQLite twin stored all of them, so a database created by
        an earlier version needs an in-place upgrade. SQLite has no
        `ADD COLUMN IF NOT EXISTS`, so the column list is inspected first.
        The late fields are added without a default: existing rows have unknown
        scope or provenance and must not be silently fabricated.
        """
        async with serialized_schema_upgrade(self._conn):
            await self._conn.execute(_SCHEMA)
            cursor = await self._conn.execute("PRAGMA table_info(learnings)")
            columns = {row[1] for row in await cursor.fetchall()}
            if "org_id" not in columns:
                await self._conn.execute(
                    "ALTER TABLE learnings ADD COLUMN org_id TEXT NOT NULL DEFAULT ''"
                )
            await _add_missing_columns(self._conn, columns)
            await self._conn.execute(_STAGE_HISTORY_SCHEMA)
            await self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_learnings_run_id ON learnings (run_id)"
            )
            await self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_learnings_scope ON learnings (org_id, agent_id, status)"
            )
            await self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_learnings_scope_axes "
                "ON learnings (org_id, team_id, user_id, agent_id, status)"
            )

    async def store(self, learning: Learning) -> int:
        """Store a learning, naming the execution that produced it.

        Resolved before the dedup probe for the same reason as the PostgreSQL
        original: the deduplicating branch returns early (#709). The probe
        receives the resolved record so a learning relying on the ambient
        `bind_execution_context` still contributes its Run to the surviving
        row's evidence when it dedupes.
        """
        provenance = observed_provenance(
            run_id=learning.run_id,
            node_run_id=learning.node_run_id,
            attempt_id=learning.attempt_id,
        )
        dedup_id = await self._bump_dedup_hit(learning, provenance)
        if dedup_id is not None:
            return dedup_id

        insert_cursor = await self._conn.execute(
            """INSERT INTO learnings
               (category, trigger_keys, learning, tool_name, source_query,
                agent_id, user_id, org_id, team_id, scope, hit_count, status,
                rca_category, rca_prevention,
                success_after_use, failure_after_use,
                run_id, node_run_id, attempt_id,
                epistemic_type, works_when, avoid_in, confidence,
                evidence_run_ids, evaluation_ids,
                applicability, reinforcement_count, contradiction_count,
                created_at, last_confirmed_at,
                stage, validated_by, validated_at, promoted_by,
                supersedes, superseded_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                learning.category,
                json.dumps(list(learning.trigger_keys)),
                learning.learning,
                learning.tool_name,
                learning.source_query,
                learning.agent_id or "",
                learning.user_id,
                learning.org_id or "",
                learning.team_id or "",
                learning.scope,
                learning.hit_count,
                learning.status,
                learning.rca_category,
                learning.rca_prevention,
                learning.success_after_use,
                learning.failure_after_use,
                *provenance.as_columns(),
                learning.epistemic_type,
                json.dumps(list(learning.works_when)),
                json.dumps(list(learning.avoid_in)),
                learning.confidence,
                json.dumps(list(learning.evidence_run_ids)),
                json.dumps(list(learning.evaluation_ids)),
                json.dumps(learning.applicability),
                learning.reinforcement_count,
                learning.contradiction_count,
                _utc_text(learning.created_at),
                _utc_text(learning.last_confirmed_at)
                if learning.last_confirmed_at is not None
                else None,
                learning.stage,
                learning.validated_by,
                _utc_text(learning.validated_at) if learning.validated_at is not None else None,
                learning.promoted_by,
                learning.supersedes,
                learning.superseded_by,
            ),
        )
        await self._conn.commit()
        return insert_cursor.lastrowid or 0

    async def _bump_dedup_hit(
        self,
        learning: Learning,
        provenance: ExecutionProvenance,
    ) -> int | None:
        """Return the id of the same-scope active row this learning dedupes into.

        The probe half of `store`: tool name, org, team, user, agent and
        `active` status must all match. The probe is scoped like the
        PostgreSQL twin's — without `org_id` here, storing a learning for org A
        could match org B's row, bump B's hit_count and return B's id to A — a
        cross-scope write and an id leak, not merely a missed insert. A match
        has its `hit_count` bumped here, where the row is in hand, so `store`
        stays a straight probe-then-insert.
        """
        cursor = await self._conn.execute(
            "SELECT id, trigger_keys, works_when, avoid_in, confidence, "
            "evidence_run_ids, evaluation_ids FROM learnings "
            "WHERE tool_name = ? AND org_id = ? AND team_id IS ? "
            "AND user_id IS ? AND agent_id IS ? AND status = 'active'",
            (
                learning.tool_name,
                learning.org_id or "",
                learning.team_id or "",
                learning.user_id,
                learning.agent_id or "",
            ),
        )
        existing = await cursor.fetchall()
        new_keys = set(learning.trigger_keys)
        for row in existing:
            existing_keys = set(json.loads(row[1]))
            if new_keys and existing_keys:
                overlap = len(new_keys & existing_keys) / len(new_keys)
                if overlap >= 0.5:
                    # Dedup consolidates: what the row says may be replaced by
                    # the reworded claim, but what it rests on unions (M4-B3).
                    # The merge runs on a throwaway Learning built from the row
                    # so `evidence.merge_applicability` stays the one rule, then
                    # only the merged columns are written back.
                    prior = Learning(
                        works_when=json.loads(row[2]),
                        avoid_in=json.loads(row[3]),
                        confidence=row[4],
                        evidence_run_ids=json.loads(row[5]),
                        evaluation_ids=json.loads(row[6]),
                    )
                    # The merge folds `incoming.run_id` into the evidence
                    # list, so it must see the ids `store` resolved, not the
                    # blank fields of a learning that leaned on the ambient
                    # context — otherwise a deduplicated write silently drops
                    # the very execution the consolidation should retain.
                    incoming = replace(
                        learning,
                        run_id=provenance.run_id,
                        node_run_id=provenance.node_run_id,
                        attempt_id=provenance.attempt_id,
                    )
                    merge_applicability(prior, incoming)
                    await self._conn.execute(
                        "UPDATE learnings SET works_when = ?, avoid_in = ?, confidence = ?, "
                        "evidence_run_ids = ?, evaluation_ids = ? WHERE id = ?",
                        (
                            json.dumps(prior.works_when),
                            json.dumps(prior.avoid_in),
                            prior.confidence,
                            json.dumps(prior.evidence_run_ids),
                            json.dumps(prior.evaluation_ids),
                            row[0],
                        ),
                    )
                    await self._conn.execute(
                        "UPDATE learnings SET hit_count = hit_count + 1 WHERE id = ?",
                        (row[0],),
                    )
                    await self._conn.commit()
                    return int(row[0])
        return None

    async def find_relevant(
        self,
        user_text: str,
        *,
        agent_id: str | None = None,
        user_id: str | None = None,
        team_id: str | None = None,
        org_id: str = "",
        max_results: int = 10,
    ) -> list[Learning]:
        """Find relevant learnings by keyword match within the requested scope.

        The org predicate is always exact, including for an empty `org_id`, so
        an unscoped caller cannot read another org's instruction. Optional
        team, user and agent predicates are also exact and are applied in SQL
        before keyword scoring. This matters because a learning is an
        instruction interpolated into the agent's *system* prompt, not a datum.

        The predicate is shared with `InMemoryLearningStore`; keeping one
        visibility rule prevents the backends from drifting again.
        """
        scope_sql, scope_params = learning_scope_predicate(
            org_id=org_id,
            team_id=team_id,
            user_id=user_id,
            agent_id=agent_id,
            placeholders=itertools.repeat("?"),
        )
        query = f"SELECT * FROM learnings WHERE status = 'active' AND {scope_sql}"
        cursor = await self._conn.execute(query, scope_params)
        columns = [d[0] for d in cursor.description]
        rows = await cursor.fetchall()

        text_lower = user_text.lower()
        scored: list[tuple[float, Learning]] = []
        for raw in rows:
            row = dict(zip(columns, raw, strict=True))
            keys: list[str] = json.loads(row["trigger_keys"])
            score: float = sum(1 for k in keys if k.lower() in text_lower)
            if score > 0:
                # Same tie-break as the in-memory twin: the epistemic bonus
                # reorders keyword ties, never overrides relevance (M4-B3).
                score += EPISTEMIC_BONUS.get(_row_to_learning(row).epistemic_type, 0.0)
                scored.append((score, _row_to_learning(row)))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [lr for _, lr in scored[:max_results]]

    async def mark_used(self, learning_ids: list[int]) -> None:
        """Increment hit_count for given IDs."""
        if not learning_ids:
            return
        placeholders = ",".join("?" for _ in learning_ids)
        await self._conn.execute(
            f"UPDATE learnings SET hit_count = hit_count + 1 WHERE id IN ({placeholders})",  # nosec B608
            learning_ids,
        )
        await self._conn.commit()

    async def produced_by(self, run_id: str, *, org_id: str = "") -> list[Learning]:
        """Return the learnings this Run produced, newest first.

        Same rule as the PostgreSQL original, including that a blank `run_id`
        returns nothing rather than every unattributed row (#709).
        """
        if not run_id:
            return []
        cursor = await self._conn.execute(
            "SELECT * FROM learnings WHERE run_id = ? AND org_id = ? ORDER BY id DESC",
            (run_id, org_id),
        )
        # `cursor.description`, not a row factory: `aiosqlite` is a
        # `TYPE_CHECKING`-only import here, and setting `row_factory` on the
        # shared connection would change what every other method on it returns.
        names = [column[0] for column in cursor.description]
        rows = await cursor.fetchall()
        return [_row_to_learning(dict(zip(names, row, strict=True))) for row in rows]

    async def mark_outcome(
        self, learning_ids: list[int], success: bool, *, org_id: str = ""
    ) -> None:
        """Increment success/failure counters per id, and re-measure confidence.

        The confidence expression is the SQL restatement of
        `evidence.outcome_confidence`: once an outcome exists, confidence IS
        the success ratio. A NULL that survives here is a row that has never
        been measured — exactly the fact promotion treats as a blocker (M4-B3).
        """
        if not learning_ids:
            return
        placeholders = ",".join("?" for _ in learning_ids)
        column = "success_after_use" if success else "failure_after_use"
        # Scoped like find_relevant: a caller may only move counters on rows it
        # could have been served. Unscoped, an id from another org would be
        # accepted and written, so a guessed id was a cross-scope write.
        await self._conn.execute(
            f"UPDATE learnings SET {column} = {column} + 1, "  # nosec B608
            # SET expressions see the pre-update row in both SQLite and
            # PostgreSQL, so the ratio is written in terms of (old value +
            # this outcome) explicitly rather than assuming the increment
            # landed first.
            "confidence = (success_after_use + CAST(? AS REAL)) / "
            "(success_after_use + failure_after_use + 1) "
            f"WHERE id IN ({placeholders}) AND org_id = ?",  # nosec B608
            [1 if success else 0, *learning_ids, org_id],
        )
        await self._conn.commit()

    async def list_ineffective(self, min_uses: int) -> list[Learning]:
        """Learnings whose failures outnumber successes over enough outcomes (#121).

        The read that turns losses into retained anti-pattern knowledge.
        Read-only, and deliberately the same predicate the in-memory store
        applies -- ``total >= min_uses`` recorded outcomes and strictly more
        failures than successes -- so no caller can tell the backends apart
        by getting a different answer. Converting what this names into
        anti-patterns is the caller's decision (the read-only
        ``IneffectiveLearningSource`` contract).
        """
        cursor = await self._conn.execute(
            """SELECT * FROM learnings
               WHERE success_after_use + failure_after_use >= ?
                 AND failure_after_use > success_after_use
               ORDER BY id DESC""",
            (min_uses,),
        )
        columns = [d[0] for d in cursor.description]
        rows = await cursor.fetchall()
        return [_row_to_learning(dict(zip(columns, row, strict=True))) for row in rows]

    async def mark_anti_pattern(
        self, learning_id: int, confidence_floor: float, *, org_id: str = ""
    ) -> bool:
        """Reclassify one row as ``anti_pattern`` at least at the floor (#121).

        The durable write half of ``list_ineffective``: the reads return
        detached copies, so a reclassification the promoter decided on a copy
        must be written back or it evaporates. Org is an exact boundary, like
        ``mark_outcome`` -- a guessed id from another scope updates nothing.
        """
        cursor = await self._conn.execute(
            """UPDATE learnings
               SET epistemic_type = 'anti_pattern',
                   confidence = MAX(confidence, ?)
               WHERE id = ? AND org_id = ?""",
            (confidence_floor, learning_id, org_id),
        )
        await self._conn.commit()
        return cursor.rowcount > 0

    async def check_auto_promotions(
        self,
        threshold: int = 5,
        org_id: str = "",
        *,
        min_confidence: float = DEFAULT_MIN_PROMOTION_CONFIDENCE,
    ) -> list[Learning]:
        """Promote learnings at threshold that also carry validation evidence.

        Candidates are filtered through the shared `promotion_blockers` verdict
        rather than a second SQL predicate: the rule lives in one place, and a
        learning missing evidence stays `active` however often it is hit
        (M4-B3).
        """
        cursor = await self._conn.execute(
            "SELECT * FROM learnings WHERE status = 'active' AND hit_count >= ? AND org_id = ?",
            (threshold, org_id),
        )
        columns = [d[0] for d in cursor.description]
        rows = await cursor.fetchall()
        candidates = [_row_to_learning(dict(zip(columns, r, strict=True))) for r in rows]
        promoted_rows = [
            lr for lr in candidates if not promotion_blockers(lr, min_confidence=min_confidence)
        ]
        if not promoted_rows:
            return []
        ids = [lr.id for lr in promoted_rows if lr.id is not None]
        placeholders = ",".join("?" for _ in ids)
        await self._conn.execute(
            f"UPDATE learnings SET status = 'promoted' WHERE id IN ({placeholders})",  # nosec B608
            ids,
        )
        await self._conn.commit()
        # The candidates were mapped before the UPDATE; the returned objects
        # must report the state the rows now hold.
        for lr in promoted_rows:
            lr.status = "promoted"
        return promoted_rows

    async def get_promoted(
        self,
        task_type: str | None = None,
        org_id: str = "",
        *,
        team_id: str | None = None,
        user_id: str | None = None,
        agent_id: str | None = None,
    ) -> list[Learning]:
        """Get promoted learnings within the requested scope."""
        scope_sql, scope_params = learning_scope_predicate(
            org_id=org_id,
            team_id=team_id,
            user_id=user_id,
            agent_id=agent_id,
            placeholders=itertools.repeat("?"),
        )
        query = f"SELECT * FROM learnings WHERE status = 'promoted' AND {scope_sql}"
        params: list[Any] = scope_params
        if task_type:
            query += " AND category = ?"
            params.append(task_type)
        cursor = await self._conn.execute(query, params)
        columns = [d[0] for d in cursor.description]
        rows = await cursor.fetchall()
        return [_row_to_learning(dict(zip(columns, r, strict=True))) for r in rows]

    async def list_all(self, org_id: str = "", limit: int = 200) -> list[Learning]:
        """List all learnings (admin endpoint)."""
        cursor = await self._conn.execute(
            "SELECT * FROM learnings WHERE org_id = ? ORDER BY id DESC LIMIT ?",
            (org_id, limit),
        )
        columns = [d[0] for d in cursor.description]
        rows = await cursor.fetchall()
        return [_row_to_learning(dict(zip(columns, r, strict=True))) for r in rows]

    async def advance_stage(
        self,
        learning_id: int,
        *,
        to_stage: LearningStage,
        actor: str,
        reason: str = "",
        org_id: str = "",
    ) -> Learning:
        """Move a learning one rung up the ladder, durably and auditably.

        The guarded UPDATE (`AND stage = <expected from>`) makes a concurrent
        double-transition fail loudly instead of applying twice, and the
        ledger row is written in the same transaction as the row update, so a
        crash between them can produce neither a moved row without a record
        nor a record without a moved row. Both writes commit together or not
        at all — that is what makes the transition *durable* (ADR-103).
        """
        row = await self._scoped_row(learning_id, org_id=org_id)
        current = LearningStage(row.get("stage") or "memory")
        candidate = _row_to_learning(row)
        updated, transition = plan_advance(candidate, to_stage=to_stage, actor=actor, reason=reason)
        cursor = await self._conn.execute(
            "UPDATE learnings SET stage = ?, validated_by = ?, promoted_by = ?, "
            "status = ? WHERE id = ? AND stage = ? AND org_id = ?",
            (
                updated.stage,
                updated.validated_by,
                updated.promoted_by,
                updated.status,
                learning_id,
                current,
                row.get("org_id") or "",
            ),
        )
        if cursor.rowcount == 0:
            # The row moved underneath us between the read and the guarded
            # UPDATE — a concurrent transition won this rung first. Raise
            # rather than half-apply: the ledger INSERT below never runs, so
            # the audit trail never records a transition the row does not
            # carry (ADR-103 rule 3; same contract as PgLearningStore's
            # `UPDATE 0`). The failed UPDATE matched no rows, so no rollback
            # is needed — the shared connection's in-flight writer is untouched.
            raise InvalidStageTransition(
                f"learning #{learning_id} left stage {candidate.stage} "
                "before the transition committed"
            )
        await self._conn.execute(
            "INSERT INTO learning_stage_transitions "
            "(learning_id, org_id, from_stage, to_stage, actor, reason) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                learning_id,
                transition.org_id,
                transition.from_stage,
                transition.to_stage,
                transition.actor,
                transition.reason,
            ),
        )
        await self._conn.commit()
        return updated

    async def stage_history(self, learning_id: int, *, org_id: str = "") -> list[StageTransition]:
        """The durable audit trail for one learning, oldest first."""
        await self._scoped_row(learning_id, org_id=org_id)
        cursor = await self._conn.execute(
            "SELECT learning_id, org_id, from_stage, to_stage, actor, reason "
            "FROM learning_stage_transitions WHERE learning_id = ? ORDER BY id",
            (learning_id,),
        )
        return [
            StageTransition(
                learning_id=int(raw[0]),
                org_id=str(raw[1] or ""),
                from_stage=LearningStage(raw[2]),
                to_stage=LearningStage(raw[3]),
                actor=str(raw[4] or ""),
                reason=str(raw[5] or ""),
            )
            for raw in await cursor.fetchall()
        ]

    async def _scoped_row(self, learning_id: int, *, org_id: str) -> dict[str, Any]:
        """The one learning row this id names, visible to this org scope.

        Same write-visibility rule as `mark_outcome`: a caller may only move
        state on rows it could have been served. An unknown id and an
        other-org id raise identically, so a guessed id leaks nothing.
        """
        cursor = await self._conn.execute(
            "SELECT * FROM learnings WHERE id = ? AND org_id = ?",
            (learning_id, org_id),
        )
        row = await cursor.fetchone()
        if row is None:
            raise KeyError(f"no learning #{learning_id} visible in this scope")
        columns = [d[0] for d in cursor.description]
        return dict(zip(columns, row, strict=True))


def _text(row: dict[str, Any], name: str) -> str:
    """Read a nullable text column as the empty string the dataclass expects.

    A nullable column and a non-optional field: a row with no producer reads
    back as a `Learning` naming none, which is the same fact in the shape the
    caller expects (#709).
    """
    return str(row.get(name) or "")


def _json_list(row: dict[str, Any], name: str) -> list[str]:
    """Read a JSON-array text column, tolerating legacy NULLs and junk."""
    raw = row.get(name)
    if not raw:
        return []
    try:
        decoded = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if isinstance(decoded, list):
        return [str(item) for item in decoded]
    return []


def _provenance_fields(row: dict[str, Any]) -> dict[str, Any]:
    """The identity, category, and provenance columns of a learnings row."""
    return {
        "id": row["id"],
        "category": row.get("category") or "",
        "trigger_keys": json.loads(row.get("trigger_keys") or "[]"),
        "learning": row["learning"],
        "tool_name": row.get("tool_name") or "",
        "source_query": _text(row, "source_query"),
        "agent_id": row.get("agent_id") or None,
        "user_id": row.get("user_id"),
        "org_id": row.get("org_id") or "",
        "team_id": _text(row, "team_id"),
        "scope": MemoryScope(row.get("scope") or "agent"),
        "hit_count": row.get("hit_count", 0),
        "status": row.get("status") or "active",
        "rca_category": row.get("rca_category"),
        "rca_prevention": row.get("rca_prevention") or "",
        "run_id": _text(row, "run_id"),
        "node_run_id": _text(row, "node_run_id"),
        "attempt_id": _text(row, "attempt_id"),
        "success_after_use": row.get("success_after_use", 0),
        "failure_after_use": row.get("failure_after_use", 0),
    }


def _lifecycle_fields(row: dict[str, Any]) -> dict[str, Any]:
    """The ladder + lifecycle + epistemics columns (ADR-103, ADR-100126-8c2d, M4-B3).

    Defaults mirror the dataclass so a pre-M4B row reads back as the local
    empirical learning on the bottom rung that it was, not as something the
    system never claimed. Applicability and provenance (M4-B3) decode with the
    same tolerance as every other column: consolidation and rewording must
    never lose the evidence a claim rests on because one column held junk.
    """
    return {
        "stage": LearningStage(row.get("stage") or "memory"),
        "epistemic_type": EpistemicType(row.get("epistemic_type") or "empirical"),
        "confidence": (
            float(row["confidence"])
            if row.get("confidence") is not None
            else DEFAULT_LEARNING_CONFIDENCE
        ),
        "works_when": _json_list(row, "works_when"),
        "avoid_in": _json_list(row, "avoid_in"),
        "evidence_run_ids": _json_list(row, "evidence_run_ids"),
        "evaluation_ids": _json_list(row, "evaluation_ids"),
        "applicability": _load_applicability(row.get("applicability")),
        "reinforcement_count": row.get("reinforcement_count") or 0,
        "contradiction_count": row.get("contradiction_count") or 0,
        "created_at": _load_moment(row.get("created_at")) or datetime.now(UTC),
        "last_confirmed_at": _load_moment(row.get("last_confirmed_at")),
        "validated_by": _text(row, "validated_by"),
        "validated_at": _load_moment(row.get("validated_at")),
        "promoted_by": _text(row, "promoted_by"),
        "supersedes": row.get("supersedes"),
        "superseded_by": row.get("superseded_by"),
    }


def _row_to_learning(row: dict[str, Any]) -> Learning:
    return Learning(**_provenance_fields(row), **_lifecycle_fields(row))


def _utc_text(moment: datetime) -> str:
    """An instant as text that sorts in instant order (see sqlite_outcomes)."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC).isoformat()
    return moment.astimezone(UTC).isoformat()


def _load_moment(raw: object) -> datetime | None:
    """Decode an instant column; NULL or unparseable text names no instant."""
    if not raw or not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _load_applicability(raw: object) -> dict[str, list[str]]:
    """Decode `applicability`, tolerating NULL or malformed text like `trigger_keys`."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return {str(k): [str(v) for v in values] for k, values in raw.items()}
    if isinstance(raw, str):
        try:
            decoded = json.loads(raw)
        except ValueError:
            return {}
        if isinstance(decoded, dict):
            return {str(k): [str(v) for v in values] for k, values in decoded.items()}
    return {}
