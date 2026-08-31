"""PostgreSQL outcome store."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from maistro.constants import THUMB_LIMIT, THUMB_WINDOW_DAYS
from maistro.observability.correlation import observed_provenance
from maistro.types.memory import Outcome

if TYPE_CHECKING:
    import asyncpg


def _scoped(query: str, params: list[Any], org_id: str = "", project_id: str = "") -> str:
    """Append the scope predicates every read here accepted and none applied.

    All five reads took an `org_id` argument and filtered on nothing, so a
    caller asking for one organization's completion rate got every
    organization's rows. `InMemoryOutcomeStore` filters on both axes, which
    makes this two implementations of one protocol disagreeing about whether
    scope means anything -- the failure mode a shared helper exists to stop
    recurring, since the defect was five copies of the same omission.

    Empty means unscoped, matching `InMemoryOutcomeStore._org_matches`: a
    caller that names no org sees everything, and one that names an org sees
    exactly that org's rows.
    """
    return query + _scope_clause(params, org_id, project_id)


def _scope_clause(params: list[Any], org_id: str = "", project_id: str = "") -> str:
    """Just the `AND col = $n` fragment, for queries that continue after WHERE.

    The aggregate reads end in GROUP BY / ORDER BY, so their predicates have to
    be interpolated at the WHERE rather than appended to the whole statement.
    Placeholder numbers come from the params list itself, which is what keeps
    the two forms consistent when a query already has positional arguments.
    """
    clause = ""
    for column, value in (("org_id", org_id), ("project_id", project_id)):
        if value:
            params.append(value)
            clause += f" AND {column} = ${len(params)}"
    return clause


class PgOutcomeStore:
    """PostgreSQL-backed outcome store."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def record(self, outcome: Outcome) -> int:
        """Record an outcome, naming the execution that produced it.

        Outcomes are what the router's scoring and the optimizer's fitness read,
        so this is the evidence path behind automated decisions -- and until
        #709 the only execution reference on it was the Conductor's DAG
        identity, which ADR-019 puts on the product side of the split.
        """
        provenance = observed_provenance(
            run_id=outcome.run_id,
            node_run_id=outcome.node_run_id,
            attempt_id=outcome.attempt_id,
        )
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                # org_id is written, not omitted: every read path on this
                # store filters by it, so an outcome recorded without one is
                # invisible to the queries that exist to find it.
                """INSERT INTO outcomes
                   (request_id, task_type, model_used, provider,
                    tool_calls, success, error_type, response_time_ms,
                    org_id, team_id, user_id, agent_id,
                    input_tokens, output_tokens, charged_microchips, pricing_version,
                    project_id, dag_id, dag_run_id, node_id,
                    thumb, thumb_comment, eval_judge_score, created_at,
                    run_id, node_run_id, attempt_id, usage_reported_calls,
                    session_id)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,
                           $17,$18,$19,$20,$21,$22,$23,$24,$25,$26,$27,$28,$29)
                   RETURNING id""",
                outcome.request_id,
                outcome.task_type,
                outcome.model_used,
                outcome.provider,
                # `json.dumps`, not `str`. asyncpg's JSONB codec takes text and
                # does not serialise Python objects, and `str([{"a": 1}])` is
                # `"[{'a': 1}]"` -- single quotes, not JSON. Every outcome that
                # actually recorded a tool call was an InvalidTextRepresentation
                # error; only the empty-list case, whose repr happens to be
                # valid JSON, ever got through.
                json.dumps(outcome.tool_calls),
                outcome.success,
                outcome.error_type,
                outcome.response_time_ms,
                # `org_id` is NOT NULL with no DDL default and was omitted
                # entirely, so every insert was a NotNullViolation -- and had it
                # had a default, the row would have silently lost the org scope
                # that `ix_outcomes_org_task` and `by_org` both key on.
                outcome.org_id,
                outcome.team_id,
                outcome.user_id,
                outcome.agent_id or "",
                outcome.input_tokens,
                outcome.output_tokens,
                outcome.charged_microchips,
                outcome.pricing_version,
                # Scope and feedback. `project_id` was dropped entirely, so a
                # failure narrative injected into one project's prompt could
                # come from another; `thumb` was dropped, so a thumbs-down
                # accepted by the feedback service became an ordinary
                # successful row and could never reach the learning loop.
                outcome.project_id,
                outcome.dag_id,
                outcome.dag_run_id,
                outcome.node_id,
                outcome.thumb,
                outcome.thumb_comment,
                outcome.eval_judge_score,
                # The fourth omission of the same kind as the three above.
                # `created_at` fell to the column's server default, so this
                # store alone decided when an outcome happened, while the
                # in-memory and SQLite twins honoured the caller's timestamp.
                # Every time-windowed read -- the completion rate, the daily
                # series, the thumbs retention window -- then answered a
                # different question here than there. `Outcome.created_at`
                # defaults to `now()`, so a caller that sets nothing is
                # unaffected (#696).
                outcome.created_at,
                # The canonical producer, beside the DAG identity rather than
                # instead of it: `dag_run_id` names a real hive-conductor object
                # the Conductor UI reads, and these name the Run/NodeRun/Attempt
                # it executes as. `as_columns` owns the "blank means absent"
                # rule, so an outcome recorded outside any execution names none
                # rather than naming a Run whose id is empty (#709).
                *provenance.as_columns(),
                # NULL, not 0, when the writer did not count: `0` would claim
                # it counted and found none, which is the conflation the
                # column exists to end (#717).
                outcome.usage_reported_calls,
                # NULL rather than "" for the same reason the provenance
                # columns take NULL: an outcome recorded outside a
                # conversation names no session, which is not the same as
                # naming a session whose id is empty (#748).
                outcome.session_id or None,
            )
            return int(row["id"]) if row else 0

    async def get_task_completion_rate(
        self,
        task_type: str = "",
        days: int = 7,
        org_id: str = "",
    ) -> dict[str, Any]:
        """Get completion rate stats."""
        cutoff = datetime.now(UTC) - timedelta(days=days)
        async with self._pool.acquire() as conn:
            query = "SELECT * FROM outcomes WHERE created_at >= $1"
            params: list[Any] = [cutoff]
            if task_type:
                params.append(task_type)
                query += f" AND task_type = ${len(params)}"
            query = _scoped(query, params, org_id)
            rows = await conn.fetch(query, *params)

        total = len(rows)
        succeeded = sum(1 for r in rows if r["success"])
        by_model: dict[str, dict[str, Any]] = {}
        for r in rows:
            m: str = r["model_used"]
            if m not in by_model:
                by_model[m] = {"total": 0, "succeeded": 0, "rate": 0.0}
            by_model[m]["total"] += 1
            if r["success"]:
                by_model[m]["succeeded"] += 1
        for v in by_model.values():
            v["rate"] = v["succeeded"] / v["total"] if v["total"] else 0.0

        return {
            "total": total,
            "succeeded": succeeded,
            "failed": total - succeeded,
            "rate": succeeded / total if total else 0.0,
            "by_model": by_model,
            "days": days,
            "task_type": task_type or "all",
        }

    async def get_usage_breakdown(
        self,
        group_by: str = "user_id",
        days: int = 7,
        org_id: str = "",
    ) -> list[dict[str, Any]]:
        """Aggregate token usage grouped by a dimension."""
        allowed = {"user_id", "team_id", "model_used", "agent_id", "provider"}
        if group_by not in allowed:
            group_by = "user_id"

        select_cols = f"""SELECT {group_by} AS grp,
                       COALESCE(SUM(input_tokens), 0) AS input_tokens,
                       COALESCE(SUM(output_tokens), 0) AS output_tokens,
                       COALESCE(SUM(input_tokens + output_tokens), 0) AS total_tokens,
                       COALESCE(SUM(charged_microchips), 0) AS total_microchips,
                       COUNT(*) AS request_count,
                       SUM(CASE WHEN success THEN 1 ELSE 0 END) AS success_count,
                       ROUND(AVG(response_time_ms)::numeric, 1) AS avg_response_ms
                   FROM outcomes"""  # nosec B608

        async with self._pool.acquire() as conn:
            if days > 0:
                cutoff = datetime.now(UTC) - timedelta(days=days)
                params: list[Any] = [cutoff]
                scope = _scope_clause(params, org_id)
                rows = await conn.fetch(
                    f"""{select_cols}
                       WHERE created_at >= $1{scope}
                       GROUP BY {group_by}
                       ORDER BY total_tokens DESC""",  # nosec B608
                    *params,
                )
            else:
                # No cutoff, so the scope predicate has to open the WHERE
                # rather than extend one. `days <= 0` means "all time", not
                # "all orgs".
                params = []
                scope = _scope_clause(params, org_id).replace(" AND ", " WHERE ", 1)
                rows = await conn.fetch(
                    f"""{select_cols}{scope}
                       GROUP BY {group_by}
                       ORDER BY total_tokens DESC""",  # nosec B608
                    *params,
                )

        return [
            {
                "group": r["grp"] or "(unknown)",
                "input_tokens": int(r["input_tokens"]),
                "output_tokens": int(r["output_tokens"]),
                "total_tokens": int(r["total_tokens"]),
                "total_microchips": int(r["total_microchips"]),
                "request_count": int(r["request_count"]),
                "success_count": int(r["success_count"]),
                "avg_response_ms": float(r["avg_response_ms"] or 0),
            }
            for r in rows
        ]

    async def get_daily_timeseries(
        self,
        group_by: str = "",
        days: int = 7,
        org_id: str = "",
    ) -> list[dict[str, Any]]:
        """Daily token usage timeseries."""
        allowed = {"user_id", "team_id", "model_used", "agent_id", "provider"}
        has_group = group_by in allowed
        cutoff = datetime.now(UTC) - timedelta(days=days)
        params: list[Any] = [cutoff]
        scope = _scope_clause(params, org_id)

        if has_group:
            query = f"""
                SELECT DATE(created_at AT TIME ZONE 'UTC') AS day,
                       {group_by} AS grp,
                       COALESCE(SUM(input_tokens), 0) AS input_tokens,
                       COALESCE(SUM(output_tokens), 0) AS output_tokens,
                       COALESCE(SUM(input_tokens + output_tokens), 0) AS total_tokens,
                       COALESCE(SUM(charged_microchips), 0) AS total_microchips,
                       COUNT(*) AS request_count
                 FROM outcomes
                 WHERE created_at >= $1{scope}
                 GROUP BY day, {group_by}
                 ORDER BY day"""  # nosec B608
        else:
            query = f"""
                SELECT DATE(created_at AT TIME ZONE 'UTC') AS day,
                       COALESCE(SUM(input_tokens), 0) AS input_tokens,
                       COALESCE(SUM(output_tokens), 0) AS output_tokens,
                       COALESCE(SUM(input_tokens + output_tokens), 0) AS total_tokens,
                       COALESCE(SUM(charged_microchips), 0) AS total_microchips,
                       COUNT(*) AS request_count
                FROM outcomes
                WHERE created_at >= $1{scope}
                GROUP BY day
                ORDER BY day"""  # nosec B608

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        return [
            {
                "date": str(r["day"]),
                "group": r["grp"] if has_group else None,
                "input_tokens": int(r["input_tokens"]),
                "output_tokens": int(r["output_tokens"]),
                "total_tokens": int(r["total_tokens"]),
                "total_microchips": int(r["total_microchips"]),
                "request_count": int(r["request_count"]),
            }
            for r in rows
        ]

    async def get_experience_context(
        self,
        task_type: str,
        tool_name: str = "",
        limit: int = 5,
        org_id: str = "",
        project_id: str = "",
    ) -> str:
        """Recent failures and thumbs-down, scoped, as a prompt section.

        Matches `InMemoryOutcomeStore.get_experience_context`, which is the
        protocol's reference implementation. Four parts of that contract were
        missing here, and each one put the wrong text into an agent's system
        prompt rather than merely returning less:

        - `org_id` and `project_id` were accepted and ignored, so a failure
          from another organization's project could be injected as this one's
          experience.
        - `tool_name` was accepted and ignored, so asking for one tool's
          failures returned every tool's.
        - thumbs-down outcomes were not surfaced at all, so user feedback never
          reached the next run's prompt. That half of the contract needed a
          `thumb` column, which is why migration 006 exists.

        The rendering is delegated to the same `_format_failure_lines` /
        `_format_thumb_lines` the in-memory store uses, so the two cannot drift
        into producing different prompts from the same rows.
        """
        from maistro.memory.outcomes import _format_failure_lines, _format_thumb_lines

        cutoff = datetime.now(UTC) - timedelta(days=7)
        params: list[Any] = [task_type, cutoff]
        query = """SELECT * FROM outcomes
                   WHERE task_type = $1 AND created_at >= $2"""
        query += _scope_clause(params, org_id, project_id)
        if tool_name:
            # `tool_calls` is JSONB, so this is a containment check against the
            # array of call objects rather than a string match -- a tool named
            # `grep` must not match a call to `grep_all`.
            params.append(json.dumps([{"name": tool_name}]))
            query += f" AND tool_calls @> ${len(params)}::jsonb"
        params.append(limit)
        limit_placeholder = len(params)

        # `created_at DESC, id DESC` then reversed, which is `[-limit:]` in SQL.
        # The in-memory store slices the tail of an append-ordered list, so it
        # renders the most recent `limit` rows *oldest first*; selecting DESC
        # and rendering as-is gave the same rows in the opposite order, and the
        # prompt an agent sees is the ordered text, not the set. `id DESC` is
        # the tiebreak: outcomes recorded inside the same clock tick have equal
        # `created_at`, and without it their relative order is whatever the
        # planner returns -- which made this a flake as well as a mismatch.
        order = f"ORDER BY created_at DESC, id DESC LIMIT ${limit_placeholder}"
        async with self._pool.acquire() as conn:
            failures = await conn.fetch(
                f"{query} AND success = false {order}",  # nosec B608
                *params,
            )
            thumbs = await conn.fetch(
                f"{query} AND success = true AND thumb = 'down' {order}",  # nosec B608
                *params,
            )

        lines = _format_failure_lines([_row_to_outcome(r) for r in reversed(failures)])
        thumb_lines = _format_thumb_lines([_row_to_outcome(r) for r in reversed(thumbs)])
        if thumb_lines:
            if lines:
                lines.append("")
            lines.extend(thumb_lines)
        return "\n".join(lines)

    async def list_outcomes(
        self,
        task_type: str = "",
        days: int = 7,
        limit: int = 50,
        org_id: str = "",
    ) -> list[Outcome]:
        """List recent outcomes."""
        cutoff = datetime.now(UTC) - timedelta(days=days)
        async with self._pool.acquire() as conn:
            query = "SELECT * FROM outcomes WHERE created_at >= $1"
            params: list[Any] = [cutoff]
            if task_type:
                params.append(task_type)
                query += f" AND task_type = ${len(params)}"
            query = _scoped(query, params, org_id)
            params.append(limit)
            query += f" ORDER BY created_at DESC LIMIT ${len(params)}"
            rows = await conn.fetch(query, *params)

        return [_row_to_outcome(r) for r in rows]

    async def list_thumbs(
        self,
        *,
        dag_id: str = "",
        days: int = THUMB_WINDOW_DAYS,
        limit: int = THUMB_LIMIT,
        org_id: str = "",
    ) -> list[Outcome]:
        """Outcomes carrying a thumb, most recent first.

        The DAG predicate is `(dag_id = $n OR dag_id = '')`, not equality: a
        thumb with no `dag_id` predates the attribution wire and belongs to
        every DAG, which is the rule `_dag_matches` states for the in-memory
        store. Pushing it into SQL rather than filtering after the LIMIT is
        what keeps the bound meaningful -- a post-filter would discard rows
        the limit had already spent.
        """
        cutoff = datetime.now(UTC) - timedelta(days=days)
        params: list[Any] = [cutoff]
        query = "SELECT * FROM outcomes WHERE created_at >= $1 AND thumb <> ''"
        if dag_id:
            params.append(dag_id)
            query += f" AND (dag_id = ${len(params)} OR dag_id = '')"
        query = _scoped(query, params, org_id)
        params.append(limit)
        query += f" ORDER BY created_at DESC LIMIT ${len(params)}"
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(query, *params)

        return [_row_to_outcome(r) for r in rows]


def _row_to_outcome(r: asyncpg.Record) -> Outcome:
    """Map a row to an `Outcome`, including the fields the store now stores.

    `org_id`, `provider`, `tool_calls` and every scope/feedback field were
    absent from the previous inline mapping, so a round-tripped `Outcome` came
    back missing the org it belonged to and the tool calls it made -- and
    `_format_thumb_lines` reads `node_id` and `thumb_comment`, so a
    thumbs-down would have rendered as `node=(unknown)` even once the columns
    existed.
    """
    return Outcome(
        id=r["id"],
        request_id=r.get("request_id", ""),
        # `or ""` because the column is nullable and the field is not: a row
        # from before 028, or one written outside a conversation, reads back as
        # an outcome naming no session.
        session_id=r.get("session_id") or "",
        task_type=r.get("task_type", ""),
        model_used=r.get("model_used", ""),
        provider=r.get("provider", ""),
        tool_calls=_load_tool_calls(r.get("tool_calls")),
        success=r["success"],
        error_type=r.get("error_type", ""),
        response_time_ms=r.get("response_time_ms", 0),
        org_id=r.get("org_id", ""),
        team_id=r.get("team_id", ""),
        user_id=r.get("user_id", ""),
        agent_id=r.get("agent_id") or None,
        input_tokens=r.get("input_tokens", 0),
        output_tokens=r.get("output_tokens", 0),
        charged_microchips=r.get("charged_microchips", 0),
        usage_reported_calls=r.get("usage_reported_calls"),
        pricing_version=r.get("pricing_version", ""),
        created_at=r.get("created_at", datetime.now(UTC)),
        project_id=r.get("project_id", ""),
        dag_id=r.get("dag_id", ""),
        dag_run_id=r.get("dag_run_id", ""),
        node_id=r.get("node_id", ""),
        run_id=r.get("run_id") or "",
        node_run_id=r.get("node_run_id") or "",
        attempt_id=r.get("attempt_id") or "",
        thumb=r.get("thumb", ""),
        thumb_comment=r.get("thumb_comment", ""),
        eval_judge_score=r.get("eval_judge_score"),
    )


def _load_tool_calls(raw: object) -> list[dict[str, object]]:
    """Decode the JSONB `tool_calls` column, which asyncpg returns as text.

    Same trap as `pg_learnings._load_keys`: the previous mapping did not read
    this column at all, and reading it naively would have handed callers a
    string where the dataclass promises a list of dicts. A row that will not
    parse costs that one outcome's tool calls, not the whole query.
    """
    if raw is None:
        return []
    if isinstance(raw, list):
        return [c for c in raw if isinstance(c, dict)]
    if isinstance(raw, str | bytes | bytearray):
        try:
            decoded = json.loads(raw)
        except (ValueError, TypeError):
            return []
        if isinstance(decoded, list):
            return [c for c in decoded if isinstance(c, dict)]
    return []
