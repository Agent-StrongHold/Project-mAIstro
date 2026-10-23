"""Workspace Attention: a read-time projection over canonical sources (#1049).

Owner decision (2026-09-25, on #1049): Attention is computed on every read
from the owners that already hold the state — human-paused NodeRuns in the
durable run store and failed Runs behind the scoped Run-inspection door. Nothing
here is persisted, and nothing here transitions anything: an item's
`answer_href` points at the canonical HITL answer route, which stays the only
way to settle a pause.

Classification uses deterministic evidence only. A persisted HITL deadline
inside the horizon makes an item time-sensitive; every other human pause and
every failed Run is queued. Age is never evidence on its own, so an item that
has merely waited a long time keeps the class it had on day one.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from routes.hitl import (
    _MAX_PENDING_SCAN_RECORDS,
    _PENDING_SCAN_PAGE_SIZE,
    PendingHumanWork,
    _pending_items,
)

from maistro.graph.durable_runs import HitlAuthorization, HitlSettlementError, cursor_time
from maistro.graph.durable_runs.hitl import hitl_deadline, settlement_time
from maistro.graph.nodes.base import PAUSE_AWAITING_HUMAN_APPROVAL, PAUSE_AWAITING_HUMAN_REVIEW
from maistro.runs.model import RunStatus
from services.dag_run_inspection import list_visible_runs
from services.dag_run_store import MAX_RUNS
from services.workspace_authority import hitl_membership_mutation_lock, is_member

#: The issue's priority ladder, most important first. Only `time_sensitive`
#: and `queued` have a deterministic producer today; the others are named so
#: ordering and `highest_class` already mean the same thing once they do.
ATTENTION_CLASSES: tuple[str, ...] = (
    "severity",
    "time_sensitive",
    "blocking",
    "queued",
    "follow_up",
    "proactive",
)

#: How close a persisted deadline must be before it raises its item.
DEFAULT_TIME_SENSITIVE_HORIZON = timedelta(hours=24)

#: Items one response returns, after ordering; the `/v1/hitl/pending` ceiling.
#: Applied only once everything scanned is classified and sorted, so a long
#: backlog of old pauses cannot push a near deadline out of the page.
_MAX_ITEMS = 200

_DECISION_REASONS = {
    PAUSE_AWAITING_HUMAN_APPROVAL: "approval",
    PAUSE_AWAITING_HUMAN_REVIEW: "review",
}


@dataclass(frozen=True)
class _Item:
    source_kind: str
    source_id: str
    workspace_id: str
    attention_class: str
    reason: str
    evidence: dict[str, Any] = field(default_factory=dict)
    answer_href: str | None = None
    deadline: datetime | None = None

    def sort_key(self) -> tuple[int, float, str]:
        return (
            ATTENTION_CLASSES.index(self.attention_class),
            self.deadline.timestamp() if self.deadline is not None else math.inf,
            self.source_id,
        )


async def _paused_records(
    user_id: str, workspace_id: str
) -> tuple[list[tuple[Any, PendingHumanWork]], bool]:
    """Human pauses in one Workspace, walked the way `/v1/hitl/pending` walks them.

    Same keyset cursor, page size, and record ceiling, and the same per-record
    revalidation against live membership before a payload is disclosed. The
    second value says whether the record ceiling stopped the walk early.
    """
    from services.dag_agents import get_run_store

    store = get_run_store()
    authorization = HitlAuthorization(
        effective_principal=user_id,
        workspace_ids=frozenset({workspace_id}),
        membership_check=is_member,
        membership_mutation_lock=hitl_membership_mutation_lock(),
    )
    found: list[tuple[Any, PendingHumanWork]] = []
    cursor: tuple[str, str] | None = None
    inspected = 0
    while inspected < _MAX_PENDING_SCAN_RECORDS:
        records = await store.list_by_status(
            RunStatus.PAUSED,
            limit=min(_PENDING_SCAN_PAGE_SIZE, _MAX_PENDING_SCAN_RECORDS - inspected),
            workspace_id=workspace_id,
            after=cursor,
        )
        if not records:
            return found, False
        inspected += len(records)
        for record in records:
            pending = _pending_items(record)
            if pending and await authorization.permits(record.run.workspace_id):
                found.extend((record, item) for item in pending)
        cursor = (cursor_time(records[-1].run.created_at), records[-1].run_id)
    return found, True


def _deadline(record: Any, node_id: str) -> datetime | None:
    try:
        return hitl_deadline(record, node_id, require_pause=False)
    except HitlSettlementError:
        # A malformed persisted deadline is not evidence of urgency.
        return None


def _human_item(
    record: Any, pending: PendingHumanWork, *, now: datetime, horizon: timedelta
) -> _Item:
    paused_reason = str(pending.payload.get("paused_reason") or "")
    decision = _DECISION_REASONS.get(paused_reason)
    if decision is not None:
        base = f"Run {pending.run_id} is blocked awaiting your {decision} at node {pending.node_id}"
    else:
        base = f"Run {pending.run_id} is waiting on your answer at node {pending.node_id}"
    deadline = _deadline(record, pending.node_id)
    answer_href: str | None = f"/v1/hitl/{pending.run_id}/{pending.node_id}/answer"
    time_sensitive = False
    reason = base
    if deadline is not None and deadline <= now:
        # The store refuses answers at or after the deadline, so offering one
        # would point the user at a door that is already shut.
        reason = f"Answer deadline passed at {deadline.isoformat()}; awaiting expiry. {base}"
        answer_href = None
    elif deadline is not None and deadline - now <= horizon:
        time_sensitive = True
        reason = f"Answer due by {deadline.isoformat()}; {base}"
    return _Item(
        source_kind="hitl_node_run",
        source_id=f"{pending.run_id}/{pending.node_id}",
        workspace_id=record.run.workspace_id,
        attention_class="time_sensitive" if time_sensitive else "queued",
        reason=reason,
        evidence={
            "paused_reason": paused_reason or None,
            "deadline": deadline.isoformat() if deadline else None,
            "paused_at": pending.paused_at,
            "payload": pending.payload,
        },
        answer_href=answer_href,
        deadline=deadline,
    )


def _failed_item(summary: dict[str, Any]) -> _Item:
    run_id = str(summary.get("id") or "")
    error = summary.get("error")
    failed_node_keys = sorted(
        str(node) for node, state in (summary.get("node_states") or {}).items() if state == "failed"
    )
    return _Item(
        source_kind="failed_run",
        source_id=run_id,
        workspace_id=str(summary.get("workspace_id") or ""),
        attention_class="queued",
        reason=f"Run {run_id} failed: {error}" if error else f"Run {run_id} failed",
        evidence={
            "error": error,
            "failed_node_keys": failed_node_keys,
            "dag_id": summary.get("dag_id") or None,
            "finished_at": summary.get("finished_at"),
        },
    )


async def _failed_runs(user_id: str, workspace_id: str) -> list[_Item]:
    runs = await list_visible_runs(user_id, limit=MAX_RUNS)
    return [
        _failed_item(summary)
        for summary in runs
        if summary.get("workspace_id") == workspace_id and summary.get("status") == "failed"
    ]


def _summary(items: list[_Item], *, truncated: bool) -> dict[str, Any]:
    counts = Counter(item.attention_class for item in items)
    return {
        "counts_by_class": {name: counts[name] for name in ATTENTION_CLASSES if counts[name]},
        "highest_class": items[0].attention_class if items else None,
        "rising": [
            item.source_id
            for item in items[:_MAX_ITEMS]
            if item.attention_class == "time_sensitive"
        ],
        "truncated": truncated,
    }


def _public(item: _Item, rank: int) -> dict[str, Any]:
    return {
        "source_kind": item.source_kind,
        "source_id": item.source_id,
        "workspace_id": item.workspace_id,
        "attention_class": item.attention_class,
        "rank": rank,
        "reason": item.reason,
        "evidence": item.evidence,
        "answer_href": item.answer_href,
    }


async def list_attention(
    user_id: str,
    workspace_id: str,
    *,
    now: datetime,
    horizon: timedelta = DEFAULT_TIME_SENSITIVE_HORIZON,
) -> dict[str, Any] | None:
    """The caller's Attention items in one Workspace, or None when not a member.

    None is also the answer for a Workspace that does not exist, so a caller
    cannot tell the two apart. Counts cover everything scanned; `rising`
    names only returned items. `truncated` means the result may be partial:
    the record ceiling stopped the walk, or `items` was cut to the page cap.
    """
    now = settlement_time(now)
    if not await is_member(user_id, workspace_id):
        return None
    paused, scan_capped = await _paused_records(user_id, workspace_id)
    items = [_human_item(record, pending, now=now, horizon=horizon) for record, pending in paused]
    items.extend(await _failed_runs(user_id, workspace_id))
    items.sort(key=_Item.sort_key)
    truncated = scan_capped or len(items) > _MAX_ITEMS
    return {
        "workspace_id": workspace_id,
        "items": [_public(item, rank) for rank, item in enumerate(items[:_MAX_ITEMS], start=1)],
        "summary": _summary(items, truncated=truncated),
    }
