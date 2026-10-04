"""PostgreSQL learning store."""

from __future__ import annotations

import itertools
import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from maistro.memory.learnings.lifecycle import (
    InvalidStageTransition,
    StageTransition,
    plan_advance,
)
from maistro.memory.vectors import EMBEDDING_DIMENSIONS, to_pgvector_literal
from maistro.observability.correlation import observed_provenance
from maistro.persistence.learning_contract import (
    LEARNING_GENERATED_FIELDS,
    LEARNING_PERSISTED_FIELDS,
)
from maistro.persistence.learning_scope import learning_scope_predicate
from maistro.types.memory import (
    DEFAULT_LEARNING_CONFIDENCE,
    EpistemicType,
    Learning,
    LearningStage,
    MemoryScope,
)

if TYPE_CHECKING:
    import asyncpg
    import asyncpg.pool

logger = logging.getLogger("maistro.persistence.learnings")

#: pgvector's filtered-recall mode for HNSW. Named so the reason for
#: `relaxed_order` over `strict_order` sits with the value rather than only
#: in the query that uses it.
_ITERATIVE_SCAN = "relaxed_order"

# Kept next to the INSERT contract so the conformance test can detect a new
# Learning field that is not represented by both persistence twins.
_PG_PERSISTED_FIELDS = LEARNING_PERSISTED_FIELDS
_PG_GENERATED_FIELDS = LEARNING_GENERATED_FIELDS
_PG_INSERT_FIELDS = (
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
    "stage",
    "epistemic_type",
    "confidence",
    "applicability",
    "reinforcement_count",
    "contradiction_count",
    "created_at",
    "last_confirmed_at",
    "validated_by",
    "validated_at",
    "supersedes",
    "superseded_by",
    "promoted_by",
)


def similarity_query(
    *, scoped_to_agent: bool, scoped_to_user: bool = False, scoped_to_team: bool = False
) -> str:
    """The SQL `find_similar` runs, built in one place.

    A module function rather than an inline string so a test can `EXPLAIN` the
    real query. The property #188 is about -- that PostgreSQL applies the scope
    filter, rather than Python applying it after an unscoped fetch -- is only
    visible in the plan, and a plan check against a hand-copied query proves
    nothing about the query that actually runs.

    The agent clause keeps the widening both SQL twins shipped: a learning
    with `agent_id = ''` is the org-wide shared pool an agent-scoped read
    still sees. `team_id`/`user_id` are exact — an empty value there means
    "not recorded", which must not republish unknown-provenance rows to every
    team or user in the org. See `persistence.learning_scope` for the shared
    rule.
    """
    clauses = [
        "status = 'active'",
        "org_id = $2",
        "embedding IS NOT NULL",
    ]
    next_placeholder = 3
    for enabled, column in (
        (scoped_to_team, "team_id"),
        (scoped_to_user, "user_id"),
        (scoped_to_agent, "agent_id"),
    ):
        if enabled:
            if column == "agent_id":
                clauses.append(f"({column} = ${next_placeholder} OR {column} = '')")
            else:
                clauses.append(f"{column} = ${next_placeholder}")
            next_placeholder += 1
    return (
        "SELECT * FROM learnings WHERE "
        + " AND ".join(clauses)
        + f" ORDER BY embedding <=> $1::vector LIMIT ${next_placeholder}"
    )


#: Fence for the belt-and-braces schema DDL below, in the style of
#: `events.pg_envelope._SCHEMA_LOCK_KEY` ("mae1") and
#: `events.pg_stores._SCHEMA_LOCK_KEY` ("mais"). `CREATE INDEX IF NOT EXISTS`'s
#: existence check and the insert into `pg_class` are not atomic across
#: processes: two replicas booting against the same database can both pass the
#: check and one dies with a duplicate key on `pg_class_relname_nsp_index`
#: (observed live on pgvector/pg18 during the #860 two-replica concurrent
#: boot). Taking a transaction-scoped advisory lock first makes the
#: check-then-create sequence a critical section, so the loser waits and then
#: sees the index already there. Key is distinct from every other advisory
#: user in the repo: "mael" = 0x6D61656C.
_SCHEMA_LOCK_KEY = 0x6D61_656C  # "mael"


class PgLearningStore:
    """PostgreSQL-backed learning store."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def ensure_schema(self) -> None:
        """Add the `org_id` column and its index if they are missing.

        ALTER-only, with no CREATE TABLE, because the table has an owner:
        `alembic/versions/` defines `learnings` and every column this class
        reads. (An earlier version of this docstring said nothing in the
        repository defined the table. That was already wrong when written —
        migration 001 creates it — and acting on it is part of how the schema
        drifted from the stores until #122 ran the two against each other.)

        What remains here is a belt-and-braces upgrade for a database migrated
        before `org_id` existed: idempotent, cheap, and safe to run at startup.
        Failing loudly on a missing scope column is the right direction for a
        filter whose absence is a cross-scope read — but the migration is what
        should be relied on, not this.

        The whole upgrade runs inside one transaction guarded by a
        transaction-scoped advisory lock: concurrently booting replicas
        serialize here instead of racing `CREATE INDEX IF NOT EXISTS`'s
        non-atomic check-then-create into a duplicate-key crash (#860 F7).
        """
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute("SELECT pg_advisory_xact_lock($1)", _SCHEMA_LOCK_KEY)
            await conn.execute(
                "ALTER TABLE learnings ADD COLUMN IF NOT EXISTS org_id TEXT NOT NULL DEFAULT ''"
            )
            # M4-B1 (ADR-103): stage columns, same belt-and-braces upgrade
            # posture as org_id. Pre-ladder rows land on the bottom rung with
            # blank actors — the truth about rows nothing validated.
            await conn.execute(
                "ALTER TABLE learnings ADD COLUMN IF NOT EXISTS "
                "stage TEXT NOT NULL DEFAULT 'memory'"
            )
            await conn.execute(
                "ALTER TABLE learnings ADD COLUMN IF NOT EXISTS "
                "validated_by TEXT NOT NULL DEFAULT ''"
            )
            await conn.execute(
                "ALTER TABLE learnings ADD COLUMN IF NOT EXISTS "
                "promoted_by TEXT NOT NULL DEFAULT ''"
            )
            # The append-only ladder audit trail. Created here as well as in
            # migration 048 for the same reason the scope index is: startup
            # may run against a database migrated before the ladder existed.
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS learning_stage_transitions (
                    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    learning_id BIGINT NOT NULL,
                    org_id TEXT NOT NULL DEFAULT '',
                    from_stage TEXT NOT NULL,
                    to_stage TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    reason TEXT NOT NULL DEFAULT '',
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_learning_stage_transitions_learning "
                "ON learning_stage_transitions (learning_id, id)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_learnings_scope "
                "ON learnings (org_id, agent_id, status)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_learnings_scope_axes "
                "ON learnings (org_id, team_id, user_id, agent_id, status)"
            )

    async def store(self, learning: Learning) -> int:
        """Store a learning, naming the execution that produced it.

        Resolved before the dedup read, not after: the deduplicating branch
        returns early, and a provenance read that only happens on the insert
        path would be a second place for the rule to live (#709).
        """
        provenance = observed_provenance(
            run_id=learning.run_id,
            node_run_id=learning.node_run_id,
            attempt_id=learning.attempt_id,
        )
        async with self._pool.acquire() as conn:
            dedup_id = await self._bump_dedup_hit(conn, learning)
            if dedup_id is not None:
                return dedup_id

            row = await conn.fetchrow(
                # source_query, team_id and hit_count are written, not
                # omitted: all three are columns the read paths select, and a
                # column the writer skips is a column that always reads back as
                # its default. `hit_count` is usually 0 on a new learning, but
                # a caller that supplies one — a re-import, a merge — must get
                # it back, and `find_relevant` orders by it. The lifecycle
                # fields (ADR-100126-8c2d) are written for the same reason: a restart
                # must not demote a validated learning back to a local belief.
                """INSERT INTO learnings
                   (category, trigger_keys, learning, tool_name, source_query,
                    agent_id, user_id, org_id, team_id, scope, hit_count, status,
                    rca_category, rca_prevention,
                    success_after_use, failure_after_use,
                    run_id, node_run_id, attempt_id,
                    stage, epistemic_type, confidence, applicability,
                    reinforcement_count, contradiction_count,
                    created_at, last_confirmed_at,
                    validated_by, validated_at,
                    supersedes, superseded_by, promoted_by)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12,
                           $13, $14, $15, $16, $17, $18, $19,
                           $20, $21, $22, $23, $24, $25, $26, $27, $28, $29,
                           $30, $31, $32)
                   RETURNING id""",
                learning.category,
                _dump_keys(learning.trigger_keys),
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
                # `as_columns` owns the "blank means absent" rule for every
                # store that writes it (#709).
                *provenance.as_columns(),
                learning.stage,
                learning.epistemic_type,
                learning.confidence,
                json.dumps(learning.applicability),
                learning.reinforcement_count,
                learning.contradiction_count,
                learning.created_at,
                learning.last_confirmed_at,
                learning.validated_by,
                learning.validated_at,
                learning.supersedes,
                learning.superseded_by,
                learning.promoted_by,
            )
            return int(row["id"]) if row else 0

    async def _bump_dedup_hit(
        self,
        conn: asyncpg.pool.PoolConnectionProxy,
        learning: Learning,
    ) -> int | None:
        """Return the id of the same-scope active row this learning dedupes into.

        The probe half of `store`: tool name, org, team, user, agent and
        `active` status must all match (scoped so storing for org A cannot bump
        org B's hit_count or hand back B's id), and at least half of the new
        trigger keys must already be present. A match has its `hit_count`
        bumped here — where the row is in hand — so `store` stays a straight
        probe-then-insert.
        """
        existing = await conn.fetch(
            """SELECT id, trigger_keys FROM learnings
               WHERE tool_name = $1 AND org_id = $2
                 AND team_id = $3 AND user_id IS NOT DISTINCT FROM $4
                 AND agent_id = $5 AND status = 'active'""",
            learning.tool_name,
            learning.org_id or "",
            learning.team_id or "",
            learning.user_id,
            learning.agent_id or "",
        )
        new_keys = set(learning.trigger_keys)
        for row in existing:
            existing_keys = set(_load_keys(row["trigger_keys"]))
            if new_keys and existing_keys:
                overlap = len(new_keys & existing_keys) / len(new_keys)
                if overlap >= 0.5:
                    await conn.execute(
                        "UPDATE learnings SET hit_count = hit_count + 1 WHERE id = $1",
                        row["id"],
                    )
                    return int(row["id"])
        return None

    async def text_of(self, learning_id: int) -> str:
        """The learning text as it is actually stored.

        `store` deduplicates, so the id it returns may belong to a row whose
        text differs from the one just submitted. A caller that embeds the
        submitted text would stamp the surviving row with a vector describing
        content it does not hold. Reading the row back is the only way to know
        what the vector should describe.
        """
        async with self._pool.acquire() as conn:
            text = await conn.fetchval("SELECT learning FROM learnings WHERE id = $1", learning_id)
        return str(text) if text else ""

    async def set_embedding(self, learning_id: int, vector: list[float]) -> None:
        """Attach an embedding to a stored learning.

        The producer half of #188. `HybridLearningStore` kept vectors in a
        process-local `dict[int, list[float]]`, so every restart threw away
        every embedding and re-embedded on next read -- which is why the column
        is the point and not an optimisation.

        Refuses a vector the schema cannot store rather than letting PostgreSQL
        raise on the cast: the error here names the learning and both widths.
        """
        if len(vector) != EMBEDDING_DIMENSIONS:
            msg = (
                f"learning {learning_id} was given a {len(vector)}-dimension embedding, "
                f"but the column is vector({EMBEDDING_DIMENSIONS}) (ADR-082326-8194)"
            )
            raise ValueError(msg)

        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE learnings SET embedding = $1::vector WHERE id = $2",
                to_pgvector_literal(vector),
                learning_id,
            )

    async def find_similar(
        self,
        query_embedding: list[float],
        *,
        org_id: str = "",
        agent_id: str | None = None,
        user_id: str | None = None,
        team_id: str | None = None,
        max_results: int = 10,
    ) -> list[Learning]:
        """Scope-filtered, similarity-ranked learnings, in one query.

        This is the whole point of putting the vector on the row (#188). The
        scope predicate is in the `WHERE` clause, so PostgreSQL applies it
        *before* returning rows -- not afterwards in Python, which is both
        slower and a scope-leak surface, because a filter that runs after the
        fetch is one a caller can forget to run.

        Ordering is by `<=>`, pgvector's cosine distance, matching
        `memory/learnings/embeddings.py::cosine_similarity` and the
        `vector_cosine_ops` index migration 007 builds. An L2-ordered query
        against a cosine index still returns rows; it just scans instead of
        using the index, which is the kind of regression only a plan check
        catches.

        `embedding IS NOT NULL` is not an optimisation: a row with no vector has
        no distance to the query, and pgvector sorts NULLs last rather than
        excluding them, so without it an unembedded corpus returns `max_results`
        arbitrary rows that look ranked.
        """
        if len(query_embedding) != EMBEDDING_DIMENSIONS:
            msg = (
                f"query embedding is {len(query_embedding)}-dimensional, but the column "
                f"is vector({EMBEDDING_DIMENSIONS}) (ADR-082326-8194)"
            )
            raise ValueError(msg)

        params: list[Any] = [to_pgvector_literal(query_embedding), org_id]
        if team_id:
            params.append(team_id)
        if user_id:
            params.append(user_id)
        if agent_id:
            params.append(agent_id)
        query = similarity_query(
            scoped_to_team=bool(team_id),
            scoped_to_user=bool(user_id),
            scoped_to_agent=bool(agent_id),
        )
        params.append(max_results)

        # HNSW searches approximately and *then* applies the scope predicate, so
        # on a large multi-org table the candidate set can be dominated by other
        # scopes and this query returns too few rows -- or none -- while
        # matching in-scope vectors exist. A small corpus never shows it,
        # because the planner picks a sequential scan and the filter is exact.
        #
        # `iterative_scan` (pgvector 0.8+) makes the index keep fetching until
        # the filtered result set is full. `relaxed_order` rather than
        # `strict_order`: strict re-sorts every batch to guarantee global
        # distance order and costs more for a ranking that is already
        # approximate. `SET LOCAL` inside the transaction, so nothing outside it
        # inherits the setting.
        async with self._pool.acquire() as conn, conn.transaction():
            await conn.execute(f"SET LOCAL hnsw.iterative_scan = {_ITERATIVE_SCAN}")
            rows = await conn.fetch(query, *params)

        return [_row_to_learning(row) for row in rows]

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

        The org predicate is always exact, including for an empty `org_id`,
        and optional team, user and agent predicates are exact as well. All
        predicates run in PostgreSQL before keyword scoring: these results are
        interpolated into the agent's system prompt, so scope filtering is an
        authorization boundary rather than a presentation filter.
        """
        scope_sql, scope_params = learning_scope_predicate(
            org_id=org_id,
            team_id=team_id,
            user_id=user_id,
            agent_id=agent_id,
            placeholders=(f"${n}" for n in itertools.count(1)),
        )
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"SELECT * FROM learnings WHERE status = 'active' AND {scope_sql}",
                *scope_params,
            )

        text_lower = user_text.lower()
        scored: list[tuple[float, Learning]] = []
        for row in rows:
            # `_load_keys`, not the raw column. asyncpg hands JSONB back as
            # text, so iterating it scored one *character* at a time: a
            # learning keyed ["timeout"] matched the query "cat" on the shared
            # letter `t`, and since almost every key shares a letter with
            # almost every query, nearly every learning scored above zero and
            # was injected into the agent's system prompt. The annotation said
            # list[str] and the value was a str, which is why it type-checked.
            keys = _load_keys(row["trigger_keys"])
            score = sum(1 for k in keys if k.lower() in text_lower)
            if score > 0:
                scored.append((float(score), _row_to_learning(row)))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [lr for _, lr in scored[:max_results]]

    async def mark_used(self, learning_ids: list[int]) -> None:
        """Increment hit_count for given IDs."""
        if not learning_ids:
            return
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE learnings SET hit_count = hit_count + 1 WHERE id = ANY($1::int[])",
                learning_ids,
            )

    async def produced_by(self, run_id: str, *, org_id: str = "") -> list[Learning]:
        """Return the learnings this Run produced, newest first.

        An empty `run_id` returns nothing rather than every row whose producer
        is NULL. "Which learnings did no execution produce" is a legitimate
        question, but it is a different one, and answering it from the same
        call means a caller with an unresolved id silently gets the wrong set.
        """
        if not run_id:
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT * FROM learnings
                   WHERE run_id = $1 AND org_id = $2
                   ORDER BY id DESC""",
                run_id,
                org_id,
            )
        return [_row_to_learning(row) for row in rows]

    async def mark_outcome(
        self, learning_ids: list[int], success: bool, *, org_id: str = ""
    ) -> None:
        """Increment success/failure counters per id."""
        if not learning_ids:
            return
        async with self._pool.acquire() as conn:
            # Scoped like find_relevant: only rows this caller could have been
            # served may have their counters moved. Ids are integers, so an
            # unscoped update accepted a guessed id from any scope.
            column = "success_after_use" if success else "failure_after_use"
            await conn.execute(
                f"UPDATE learnings SET {column} = {column} + 1 "  # nosec B608
                "WHERE id = ANY($1::int[]) AND org_id = $2",
                learning_ids,
                org_id,
            )

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
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT * FROM learnings
                   WHERE success_after_use + failure_after_use >= $1
                     AND failure_after_use > success_after_use
                   ORDER BY id DESC""",
                min_uses,
            )
        return [_row_to_learning(row) for row in rows]

    async def mark_anti_pattern(
        self, learning_id: int, confidence_floor: float, *, org_id: str = ""
    ) -> bool:
        """Reclassify one row as ``anti_pattern`` at least at the floor (#121).

        The durable write half of ``list_ineffective``: the reads return
        detached copies, so a reclassification the promoter decided on a copy
        must be written back or it evaporates. Org is an exact boundary, like
        ``mark_outcome`` -- a guessed id from another scope updates nothing.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """UPDATE learnings
                   SET epistemic_type = 'anti_pattern',
                       confidence = GREATEST(confidence, $2)
                   WHERE id = $1 AND org_id = $3
                   RETURNING id""",
                learning_id,
                confidence_floor,
                org_id,
            )
            return row is not None

    async def check_auto_promotions(
        self,
        threshold: int = 5,
        org_id: str = "",
    ) -> list[Learning]:
        """Promote learnings with hit_count >= threshold."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """UPDATE learnings SET status = 'promoted'
                   WHERE status = 'active' AND hit_count >= $1
                     AND org_id = $2
                   RETURNING *""",
                threshold,
                org_id,
            )
            return [_row_to_learning(r) for r in rows]

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
            placeholders=(f"${n}" for n in itertools.count(1)),
        )
        query = f"SELECT * FROM learnings WHERE status = 'promoted' AND {scope_sql}"
        params: list[Any] = scope_params
        if task_type:
            query += f" AND category = ${len(params) + 1}"
            params.append(task_type)
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [_row_to_learning(r) for r in rows]

    async def list_all(self, org_id: str = "", limit: int = 200) -> list[Learning]:
        """List all learnings (admin endpoint)."""
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM learnings WHERE org_id = $1 ORDER BY id DESC LIMIT $2",
                org_id,
                limit,
            )
            return [_row_to_learning(r) for r in rows]

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

        One transaction does both writes: the guarded row UPDATE (`AND
        stage = $from` makes a concurrent double-transition fail loudly
        rather than apply twice) and the append-only ledger row. A crash
        between them can produce neither a moved row without a record nor a
        record without a moved row — that is what makes the transition
        durable (ADR-103).
        """
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                "SELECT * FROM learnings WHERE id = $1 AND org_id = $2",
                learning_id,
                org_id,
            )
            if row is None:
                raise KeyError(f"no learning #{learning_id} visible in this scope")
            candidate = _row_to_learning(row)
            updated, transition = plan_advance(
                candidate, to_stage=to_stage, actor=actor, reason=reason
            )
            result = await conn.execute(
                "UPDATE learnings SET stage = $2, validated_by = $3, "
                "promoted_by = $4, status = $5 "
                "WHERE id = $1 AND stage = $6 AND org_id = $7",
                learning_id,
                updated.stage,
                updated.validated_by,
                updated.promoted_by,
                updated.status,
                candidate.stage,
                org_id,
            )
            if result == "UPDATE 0":
                # The row moved underneath us between the SELECT and the
                # UPDATE. Raise rather than half-apply: the ledger must never
                # record a transition the row does not carry.
                raise InvalidStageTransition(
                    f"learning #{learning_id} left stage {candidate.stage} "
                    "before the transition committed"
                )
            await conn.execute(
                "INSERT INTO learning_stage_transitions "
                "(learning_id, org_id, from_stage, to_stage, actor, reason) "
                "VALUES ($1, $2, $3, $4, $5, $6)",
                learning_id,
                transition.org_id,
                transition.from_stage,
                transition.to_stage,
                transition.actor,
                transition.reason,
            )
        return updated

    async def stage_history(self, learning_id: int, *, org_id: str = "") -> list[StageTransition]:
        """The durable audit trail for one learning, oldest first."""
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT 1 FROM learnings WHERE id = $1 AND org_id = $2",
                learning_id,
                org_id,
            )
            if row is None:
                raise KeyError(f"no learning #{learning_id} visible in this scope")
            rows = await conn.fetch(
                "SELECT learning_id, org_id, from_stage, to_stage, actor, reason "
                "FROM learning_stage_transitions WHERE learning_id = $1 ORDER BY id",
                learning_id,
            )
        return [
            StageTransition(
                learning_id=int(raw["learning_id"]),
                org_id=str(raw["org_id"] or ""),
                from_stage=LearningStage(raw["from_stage"]),
                to_stage=LearningStage(raw["to_stage"]),
                actor=str(raw["actor"] or ""),
                reason=str(raw["reason"] or ""),
            )
            for raw in rows
        ]


def _dump_keys(keys: list[str]) -> str:
    """Encode `trigger_keys` for the JSONB column migration 001 declares.

    asyncpg's default JSONB codec is `str` in both directions -- it does not
    serialise Python objects. Passing a `list` raised, and reading a row back
    with `list(row["trigger_keys"])` split the raw JSON *text* into single
    characters, so a stored `["timeout", "retry"]` came back as
    `['[', '"', 't', 'i', ...]`. The write half failed loudly and the read half
    corrupted silently.

    The conversion lives here rather than in a pool-level `set_type_codec`
    because a store whose correctness depends on how someone else constructed
    the pool is the same class of hidden coupling that produced #122. This one
    is right however it is wired.
    """
    return json.dumps(list(keys))


def _load_keys(raw: object) -> list[str]:
    """Decode `trigger_keys`, tolerating a pool that *does* register a codec.

    Returns `[]` for NULL or for text that is not a JSON array of strings,
    rather than raising: a malformed row should cost that one learning, not
    every query that happens to touch it.
    """
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(k) for k in raw]
    if isinstance(raw, str | bytes | bytearray):
        try:
            decoded = json.loads(raw)
        except (ValueError, TypeError):
            return []
        if isinstance(decoded, list):
            return [str(k) for k in decoded]
    return []


def _provenance_fields(row: asyncpg.Record) -> dict[str, Any]:
    """The identity, category, and provenance columns of a learnings row."""
    return {
        "id": row["id"],
        "category": row.get("category") or "",
        "trigger_keys": _load_keys(row.get("trigger_keys")),
        "learning": row["learning"],
        "tool_name": row.get("tool_name", ""),
        # Preserve both the provenance query and team scope on reads; they are
        # part of the Learning contract, not write-only SQL columns.
        "source_query": row.get("source_query", ""),
        "agent_id": row.get("agent_id") or None,
        "user_id": row.get("user_id"),
        "org_id": row.get("org_id") or "",
        "team_id": row.get("team_id") or "",
        "scope": MemoryScope(row.get("scope") or "agent"),
        "hit_count": row.get("hit_count", 0),
        "status": row.get("status", "active"),
        "rca_category": row.get("rca_category"),
        "rca_prevention": row.get("rca_prevention", ""),
        "success_after_use": row.get("success_after_use", 0),
        "failure_after_use": row.get("failure_after_use", 0),
        # `or ""` because the columns are nullable and the dataclass fields are
        # not: a row with no producer comes back as a Learning naming none,
        # which is the same fact in the shape the caller expects (#709).
        "run_id": row.get("run_id") or "",
        "node_run_id": row.get("node_run_id") or "",
        "attempt_id": row.get("attempt_id") or "",
    }


def _lifecycle_fields(row: asyncpg.Record) -> dict[str, Any]:
    """The ladder + lifecycle + epistemics columns (ADR-103, ADR-100126-8c2d).

    Defaults mirror the dataclass so a row written before migration 052 reads
    back as the local empirical learning on the bottom rung that it was, not
    as something the system never claimed.
    """
    return {
        "stage": LearningStage(row.get("stage") or "memory"),
        "epistemic_type": EpistemicType(row.get("epistemic_type") or "empirical"),
        "confidence": (
            float(row["confidence"])
            if row.get("confidence") is not None
            else DEFAULT_LEARNING_CONFIDENCE
        ),
        "applicability": _load_applicability(row.get("applicability")),
        "reinforcement_count": row.get("reinforcement_count") or 0,
        "contradiction_count": row.get("contradiction_count") or 0,
        "created_at": row.get("created_at") or datetime.now(UTC),
        "last_confirmed_at": row.get("last_confirmed_at"),
        "validated_by": row.get("validated_by") or "",
        "validated_at": row.get("validated_at"),
        "supersedes": row.get("supersedes"),
        "superseded_by": row.get("superseded_by"),
        "promoted_by": row.get("promoted_by") or "",
    }


def _row_to_learning(row: asyncpg.Record) -> Learning:
    return Learning(**_provenance_fields(row), **_lifecycle_fields(row))


def _load_applicability(raw: object) -> dict[str, list[str]]:
    """Decode `applicability`, tolerating NULL or malformed text like `_load_keys`."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return {str(k): [str(v) for v in values] for k, values in raw.items()}
    if isinstance(raw, str | bytes | bytearray):
        try:
            decoded = json.loads(raw)
        except (ValueError, TypeError):
            return {}
        if isinstance(decoded, dict):
            return {str(k): [str(v) for v in values] for k, values in decoded.items()}
    return {}
