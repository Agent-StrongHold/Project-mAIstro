"""In-memory outcome store (ADR-017).

Ported from Stronghold: task completion rate, experience-augmented prompts,
usage breakdown, and daily timeseries.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from maistro.constants import THUMB_LIMIT, THUMB_WINDOW_DAYS
from maistro.memory.types import Outcome

MAX_OUTCOMES = 10_000


def _format_failure_lines(failures: list[Outcome]) -> list[str]:
    """Render hard-failure outcomes as a markdown section (empty list if none)."""
    if not failures:
        return []
    lines = ["## Recent Failure Patterns"]
    for o in failures:
        error = o.error_type or "unknown"
        lines.append(f"- {error} (model: {o.model_used})")
    return lines


def _format_thumb_lines(thumb_downs: list[Outcome]) -> list[str]:
    """Render thumbs-down outcomes as a markdown section (empty list if none)."""
    if not thumb_downs:
        return []
    lines = ["## User Thumbs-Down Patterns"]
    for o in thumb_downs:
        comment = (o.thumb_comment or "").strip()
        tail = f" — {comment}" if comment else ""
        lines.append(f"- node={o.node_id or '(unknown)'} task={o.task_type}{tail}")
    return lines


def _dag_matches(record_dag: str, caller_dag: str) -> bool:
    """Whether a thumb belongs to the DAG being asked about.

    Empty on either side matches: a caller naming no DAG wants all of them,
    and a thumb carrying no `dag_id` predates the attribution wire, so
    excluding it would silently discard feedback a user actually gave. That
    second half is the rule the optimizer already applied inline, kept here
    where all three stores can share one definition of it (#696).
    """
    if not caller_dag or not record_dag:
        return True
    return record_dag == caller_dag


class InMemoryOutcomeStore:
    def __init__(self, max_outcomes: int = MAX_OUTCOMES) -> None:
        self._outcomes: list[Outcome] = []
        self._next_id = 1
        self._max = max_outcomes

    async def record(self, outcome: Outcome) -> int:
        if len(self._outcomes) >= self._max:
            self._outcomes.pop(0)
        outcome.id = self._next_id
        self._next_id += 1
        self._outcomes.append(outcome)
        return outcome.id

    async def get_task_completion_rate(
        self,
        task_type: str = "",
        days: int = 7,
        org_id: str = "",
    ) -> dict[str, Any]:
        cutoff = datetime.now(UTC) - timedelta(days=days)
        filtered = [
            o
            for o in self._outcomes
            if o.created_at >= cutoff
            and (not task_type or o.task_type == task_type)
            and self._org_matches(o.org_id, org_id)
        ]

        total = len(filtered)
        succeeded = sum(1 for o in filtered if o.success)
        failed = total - succeeded

        by_model: dict[str, dict[str, Any]] = {}
        for o in filtered:
            if o.model_used not in by_model:
                by_model[o.model_used] = {"total": 0, "succeeded": 0}
            by_model[o.model_used]["total"] += 1
            if o.success:
                by_model[o.model_used]["succeeded"] += 1

        for stats in by_model.values():
            stats["rate"] = stats["succeeded"] / max(stats["total"], 1)

        return {
            "total": total,
            "succeeded": succeeded,
            "failed": failed,
            "rate": succeeded / max(total, 1),
            "by_model": by_model,
            "days": days,
            "task_type": task_type or "all",
        }

    async def get_experience_context(
        self,
        task_type: str,
        tool_name: str = "",
        limit: int = 5,
        org_id: str = "",
        project_id: str = "",
    ) -> str:
        """Get recent failure + user-thumbs-down patterns as a prompt section.

        New in Phase 2: `project_id` filter. When provided, only outcomes
        recorded against that project are surfaced — a thumbs-down on a node
        in Project A never pollutes Project B's prompt context. Default ""
        keeps backward compatibility (returns the cross-project narrative).

        New in Phase 2: thumbs-down outcomes are surfaced alongside hard
        failures so user feedback flows into the next run's prompt.
        """
        cutoff = datetime.now(UTC) - timedelta(days=7)

        def _matches(o: Outcome) -> bool:
            if o.task_type != task_type:
                return False
            if o.created_at < cutoff:
                return False
            if tool_name and not any(tc.get("name") == tool_name for tc in o.tool_calls):
                return False
            if not self._org_matches(o.org_id, org_id):
                return False
            return not (project_id and o.project_id != project_id)

        # Two signal types: hard failures (success=False) and user thumbs-down.
        hard_failures = [o for o in self._outcomes if _matches(o) and not o.success]
        thumb_downs = [o for o in self._outcomes if _matches(o) and o.success and o.thumb == "down"]

        if not hard_failures and not thumb_downs:
            return ""

        lines: list[str] = []
        lines.extend(_format_failure_lines(hard_failures[-limit:]))

        thumb_lines = _format_thumb_lines(thumb_downs[-limit:])
        if thumb_lines:
            if lines:
                lines.append("")
            lines.extend(thumb_lines)

        return "\n".join(lines)

    async def get_usage_breakdown(
        self,
        group_by: str = "user_id",
        days: int = 7,
        org_id: str = "",
    ) -> list[dict[str, Any]]:
        """Aggregate token usage grouped by a dimension."""
        cutoff = datetime.now(UTC) - timedelta(days=days)
        filtered = [
            o
            for o in self._outcomes
            if o.created_at >= cutoff and self._org_matches(o.org_id, org_id)
        ]

        groups: dict[str, dict[str, Any]] = {}
        for o in filtered:
            key = getattr(o, group_by, "") or "(unknown)"
            if key not in groups:
                groups[key] = {
                    "group": key,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "request_count": 0,
                    "success_count": 0,
                    "total_microchips": 0,
                    "avg_response_ms": 0.0,
                    "_total_ms": 0,
                }
            g = groups[key]
            g["input_tokens"] += o.input_tokens
            g["output_tokens"] += o.output_tokens
            g["total_tokens"] += o.input_tokens + o.output_tokens
            g["total_microchips"] += getattr(o, "charged_microchips", 0)
            g["request_count"] += 1
            if o.success:
                g["success_count"] += 1
            g["_total_ms"] += o.response_time_ms

        result = []
        for g in groups.values():
            if g["request_count"] > 0:
                g["avg_response_ms"] = round(g["_total_ms"] / g["request_count"], 1)
            del g["_total_ms"]
            result.append(g)

        result.sort(key=lambda x: x["total_tokens"], reverse=True)
        return result

    async def get_daily_timeseries(
        self,
        group_by: str = "",
        days: int = 7,
        org_id: str = "",
    ) -> list[dict[str, Any]]:
        """Daily token usage timeseries, optionally grouped."""
        cutoff = datetime.now(UTC) - timedelta(days=days)
        filtered = [
            o
            for o in self._outcomes
            if o.created_at >= cutoff and self._org_matches(o.org_id, org_id)
        ]

        buckets: dict[str, dict[str, Any]] = {}
        for o in filtered:
            day_str = o.created_at.strftime("%Y-%m-%d")
            grp = getattr(o, group_by, "") if group_by else "__all__"
            key = f"{day_str}|{grp}"
            if key not in buckets:
                buckets[key] = {
                    "date": day_str,
                    "group": grp if group_by else None,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "total_microchips": 0,
                    "request_count": 0,
                }
            b = buckets[key]
            b["input_tokens"] += o.input_tokens
            b["output_tokens"] += o.output_tokens
            b["total_tokens"] += o.input_tokens + o.output_tokens
            b["total_microchips"] += getattr(o, "charged_microchips", 0)
            b["request_count"] += 1

        result = sorted(buckets.values(), key=lambda x: x["date"])
        return result

    async def list_outcomes(
        self,
        task_type: str = "",
        days: int = 7,
        limit: int = 50,
        org_id: str = "",
    ) -> list[Outcome]:
        """List recent outcomes."""
        cutoff = datetime.now(UTC) - timedelta(days=days)
        filtered = [
            o
            for o in self._outcomes
            if o.created_at >= cutoff
            and (not task_type or o.task_type == task_type)
            and self._org_matches(o.org_id, org_id)
        ]
        return filtered[-limit:]

    async def list_thumbs(
        self,
        *,
        dag_id: str = "",
        days: int = THUMB_WINDOW_DAYS,
        limit: int = THUMB_LIMIT,
        org_id: str = "",
    ) -> list[Outcome]:
        """Outcomes carrying a thumb, most recent first."""
        cutoff = datetime.now(UTC) - timedelta(days=days)
        matched = [
            o
            for o in self._outcomes
            if o.thumb
            and o.created_at >= cutoff
            and _dag_matches(o.dag_id, dag_id)
            and self._org_matches(o.org_id, org_id)
        ]
        # Sorted, not reversed. Insertion order equals timestamp order only
        # while every write is "now"; a backfill, an import or a delayed event
        # breaks that, and then a small `limit` would drop a newer thumb and
        # keep an older one -- while the two SQL twins, which order by
        # `created_at DESC`, answered correctly. Three implementations of one
        # protocol have to agree about which thumbs are the recent ones (#696).
        matched.sort(key=lambda o: o.created_at, reverse=True)
        return matched[:limit]

    @staticmethod
    def _org_matches(record_org: str, caller_org: str) -> bool:
        if not caller_org:
            return True
        return record_org == caller_org
