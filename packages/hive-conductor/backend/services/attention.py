"""Workspace Attention: a read-time projection over canonical sources (#1049).

Owner decision (2026-09-25, on #1049): Attention is computed on every read
from the owners that already hold the state — human-paused NodeRuns in the
durable run store, failed Runs behind the scoped Run-inspection door, unread
agent messages, and pending optimizer proposals. An item's ``answer_href``
points at the canonical HITL answer route when the source is a pause; other
owners keep their own settle doors (optimizer accept/reject, message read).

The one thing this module may persist is a **defer/dismiss preference**
(same shape as Home adaptive dismissals): evidence that the user asked not
to see a source id in this Workspace. That is not a second Attention store
and does not transition HITL/Run/message/proposal state.

Classification uses deterministic evidence only. A persisted HITL deadline
inside the horizon makes an item time-sensitive; every other human pause and
every failed Run is queued. Unread critical messages are severity; unread
warnings are queued; unread info and pending optimizer proposals enter as
proactive (Waiting). Age is never evidence on its own, so an item that has
merely waited a long time keeps the class it had on day one.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import stores
from routes.hitl import PendingHumanWork, _pending_items

from maistro.graph.durable_runs import (
    MAX_PENDING_SCAN_RECORDS,
    HitlAuthorization,
    HitlSettlementError,
    pending_hitl_records,
)
from maistro.graph.durable_runs.hitl import hitl_deadline, settlement_time
from maistro.graph.nodes.base import PAUSE_AWAITING_HUMAN_APPROVAL, PAUSE_AWAITING_HUMAN_REVIEW
from services.dag_run_inspection import list_visible_runs
from services.dag_run_store import MAX_RUNS
from services.model_store import JsonStore
from services.optimizer import DECISION_PENDING, list_proposals
from services.workspace_authority import hitl_membership_mutation_lock, is_member

DISMISSALS_STORE = "attention_dismissals"
dismissal_store: JsonStore = stores.register_json_store(JsonStore(DISMISSALS_STORE))

#: Priority ladder (#1049), most important first:
#: severity > time_sensitive > blocking > queued > follow_up > proactive.
ATTENTION_CLASSES: tuple[str, ...] = (
    "severity",
    "time_sensitive",
    "blocking",
    "queued",
    "follow_up",
    "proactive",
)

#: Interruption vocabulary from the issue (blocking / popup / queued / waiting),
#: derived from the priority class so UI never invents ranking client-side.
INTERRUPTION_FOR_CLASS: dict[str, str] = {
    "severity": "blocking",
    "time_sensitive": "popup",
    "blocking": "blocking",
    "queued": "queued",
    "follow_up": "waiting",
    "proactive": "waiting",
}

#: How close a persisted deadline must be before it raises its item.
DEFAULT_TIME_SENSITIVE_HORIZON = timedelta(hours=24)

#: Optimizer proposals at or above this priority_score count as "valuable"
#: Waiting for the quality indicator (not an escalation by themselves).
_VALUABLE_PROPOSAL_SCORE = 0.5

#: Items one response returns, after ordering; the `/v1/hitl/pending` ceiling.
#: Applied only once everything scanned is classified and sorted, so a long
#: backlog of old pauses cannot push a near deadline out of the page.
_MAX_ITEMS = 200

_DECISION_REASONS = {
    PAUSE_AWAITING_HUMAN_APPROVAL: "approval",
    PAUSE_AWAITING_HUMAN_REVIEW: "review",
}

_MESSAGE_CLASS: dict[str, str] = {
    "critical": "severity",
    "warning": "queued",
    "info": "proactive",
}

#: Wired from ``main`` (already an importer of ``routes.messages``) so this
#: module never gains a retirement-ledger edge on the messages router/store.
_MessageRows = Callable[..., list[dict[str, Any]]]
_message_rows_provider: _MessageRows | None = None


def set_message_rows_provider(provider: _MessageRows | None) -> None:
    """Install the canonical messages list callable (MessageBoard MERGE)."""
    global _message_rows_provider
    _message_rows_provider = provider


def _message_rows() -> list[dict[str, Any]]:
    if _message_rows_provider is None:
        return []
    return list(_message_rows_provider())


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
) -> tuple[list[tuple[Any, PendingHumanWork]], bool, bool]:
    """Human pauses in one Workspace, walked the way `/v1/hitl/pending` walks them.

    The same canonical walk (`pending_hitl_records`, #1109): the store's
    pause-kind projection decides human eligibility before any page is cut,
    and each item-carrying record is revalidated against live membership
    before its payload is disclosed. Workspace-wide (no Project named), the
    continuation index cannot carry Workspace scope, so the store filters it
    from each assembled page and keeps paging — a page of another tenant's
    rows advances the walk instead of ending it, and this Workspace's work
    behind such pages is still reached within one request's inspection
    ceiling. What the second value reports is the one honest remaining cap:
    the record ceiling stopped the walk early, so a later read may find more.

    The third value is ``True`` when the canonical graph spine is not wired
    (standalone Conductor / e2e without a Container). HITL pauses cannot be
    read then — that is an unavailable source, not an empty queue — but
    failed-Run projections still answer, so Attention stays a 200 read
    rather than a 500 for a missing HITL owner.
    """
    from services.dag_agents import CanonicalGraphUnavailable, get_run_store

    try:
        store = get_run_store()
    except CanonicalGraphUnavailable:
        return [], False, True

    authorization = HitlAuthorization(
        effective_principal=user_id,
        workspace_ids=frozenset({workspace_id}),
        membership_check=is_member,
        membership_mutation_lock=hitl_membership_mutation_lock(),
    )
    scan = await pending_hitl_records(
        store,
        authorization=authorization,
        workspace_id=workspace_id,
        project_id=None,
        limit=MAX_PENDING_SCAN_RECORDS,
    )
    found: list[tuple[Any, PendingHumanWork]] = []
    for record in scan.records:
        for item in _pending_items(record):
            found.append((record, item))
    return found, not scan.exhausted, False


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


def _message_item(row: dict[str, Any], *, workspace_id: str) -> _Item | None:
    """Unread agent message → Attention class (MessageBoard MERGE, #1049).

    Messages have no Workspace column today: they are intentionally
    user-global notifications projected into every Workspace the caller can
    read. Critical → severity (blocking interruption); warning → queued;
    info → proactive (Waiting). Read rows stay off the projection.
    """
    if row.get("read"):
        return None
    msg_id = str(row.get("id") or "")
    if not msg_id:
        return None
    priority = str(row.get("priority") or "info")
    attention_class = _MESSAGE_CLASS.get(priority, "proactive")
    subject = str(row.get("subject") or "(no subject)")
    from_agent = str(row.get("from_agent") or "agent")
    category = str(row.get("category") or "general")
    return _Item(
        source_kind="agent_message",
        source_id=msg_id,
        workspace_id=workspace_id,
        attention_class=attention_class,
        reason=f"Message from {from_agent}: {subject}",
        evidence={
            "from_agent": from_agent,
            "to": row.get("to"),
            "subject": subject,
            "body": row.get("body"),
            "priority": priority,
            "category": category,
            "created_at": row.get("created_at"),
            "synthetic": bool(row.get("synthetic")),
            "user_global": True,
            "interruption": INTERRUPTION_FOR_CLASS[attention_class],
        },
        answer_href=None,
    )


def _message_items(*, workspace_id: str) -> list[_Item]:
    # Provider is installed by main from routes.messages.list_messages so
    # Attention does not become a new importer of a retiring surface (#1046).
    items: list[_Item] = []
    for row in _message_rows():
        if not isinstance(row, dict):
            continue
        item = _message_item(row, workspace_id=workspace_id)
        if item is not None:
            items.append(item)
    return items


def _optimizer_item(row: dict[str, Any], *, workspace_id: str) -> _Item | None:
    """Pending optimizer proposal → proactive Waiting (OptimizationInbox MERGE).

    Only proposals whose ``workspace_id`` matches are projected, so one
    Workspace's suggestions never bleed into another. Accept/reject stay on
    the canonical optimizer routes — Attention does not terminalize them.
    """
    if str(row.get("decision") or "") != DECISION_PENDING:
        return None
    if str(row.get("workspace_id") or "") != workspace_id:
        return None
    proposal_id = str(row.get("id") or "")
    if not proposal_id:
        return None
    dag_id = str(row.get("dag_id") or "")
    kind = str(row.get("kind") or "proposal")
    rationale = str(row.get("rationale") or "").strip()
    score = float(row.get("priority_score") or 0.0)
    reason = (
        f"Optimizer suggests {kind} on DAG {dag_id}: {rationale}"
        if rationale
        else f"Optimizer suggests {kind} on DAG {dag_id}"
    )
    return _Item(
        source_kind="optimizer_proposal",
        source_id=proposal_id,
        workspace_id=workspace_id,
        attention_class="proactive",
        reason=reason,
        evidence={
            "dag_id": dag_id or None,
            "kind": kind,
            "field_path": row.get("field_path"),
            "rationale": rationale or None,
            "priority_score": score,
            "class": row.get("class"),
            "blocked_by_edit_lock": bool(row.get("blocked_by_edit_lock")),
            "interruption": "waiting",
            "accept_href": f"/v1/optimizer/proposals/{proposal_id}/accept",
            "reject_href": f"/v1/optimizer/proposals/{proposal_id}/reject",
        },
        answer_href=None,
    )


def _optimizer_items(*, workspace_id: str) -> list[_Item]:
    # Read through services.optimizer.list_proposals (already an allowed
    # importer of optimizer_proposals) so Attention does not gain a store edge.
    items: list[_Item] = []
    for row in list_proposals(decision=DECISION_PENDING, limit=_MAX_ITEMS):
        if not isinstance(row, dict):
            continue
        item = _optimizer_item(row, workspace_id=workspace_id)
        if item is not None:
            items.append(item)
    return items


def _dismissal_key(workspace_id: str, source_kind: str, source_id: str) -> str:
    return f"{workspace_id}:{source_kind}:{source_id}"


def record_dismissal(
    workspace_id: str,
    source_kind: str,
    source_id: str,
    *,
    actor: str,
    action: str = "dismiss",
) -> dict[str, Any]:
    """Record defer/dismiss for one Attention source id (preference evidence).

    Does not settle HITL or change Run state. Keyed by Workspace + source so
    another Workspace's Attention is never filtered by this preference.
    """
    if not source_kind or not source_id:
        raise ValueError("an Attention dismissal names source_kind and source_id")
    if action not in {"dismiss", "defer"}:
        raise ValueError("action must be dismiss or defer")
    key = _dismissal_key(workspace_id, source_kind, source_id)
    now = datetime.now(UTC)
    prior = dismissal_store.get(key)
    prior_count = int(prior.get("count", 0)) if isinstance(prior, dict) else 0
    prior_first = prior.get("first_at") if isinstance(prior, dict) else None
    record = {
        "workspace_id": workspace_id,
        "source_kind": source_kind,
        "source_id": source_id,
        "action": action,
        "count": prior_count + 1,
        "first_at": prior_first or now.isoformat(),
        "last_at": now.isoformat(),
        "dismissed_by": actor,
    }
    dismissal_store[key] = record
    return record


def clear_dismissal(workspace_id: str, source_kind: str, source_id: str) -> bool:
    """Forget a defer/dismiss preference. Returns True when a row was removed."""
    key = _dismissal_key(workspace_id, source_kind, source_id)
    if key in dismissal_store:
        dismissal_store.pop(key)
        return True
    return False


def dismissed_source_ids(workspace_id: str) -> set[tuple[str, str]]:
    """``(source_kind, source_id)`` pairs hidden for this Workspace."""
    prefix = f"{workspace_id}:"
    out: set[tuple[str, str]] = set()
    for key, record in dismissal_store.items():
        if not key.startswith(prefix) or not isinstance(record, dict):
            continue
        kind = str(record.get("source_kind") or "")
        sid = str(record.get("source_id") or "")
        if kind and sid:
            out.add((kind, sid))
    return out


def _waiting_quality(items: list[_Item]) -> dict[str, Any]:
    """Compact Waiting indicator: count + unusually valuable ids (not a rank invent)."""
    waiting = [
        item for item in items if INTERRUPTION_FOR_CLASS.get(item.attention_class) == "waiting"
    ]
    valuable: list[str] = []
    for item in waiting:
        if item.source_kind == "optimizer_proposal":
            score = item.evidence.get("priority_score")
            if isinstance(score, (int, float)) and float(score) >= _VALUABLE_PROPOSAL_SCORE:
                valuable.append(item.source_id)
        elif item.attention_class == "follow_up":
            valuable.append(item.source_id)
    return {
        "count": len(waiting),
        "valuable_source_ids": valuable[:_MAX_ITEMS],
    }


def _summary(
    items: list[_Item],
    *,
    truncated: bool,
    hitl_unavailable: bool,
    dismissed_count: int,
) -> dict[str, Any]:
    counts = Counter(item.attention_class for item in items)
    interruptions = Counter(
        INTERRUPTION_FOR_CLASS[item.attention_class]
        for item in items
        if item.attention_class in INTERRUPTION_FOR_CLASS
    )
    return {
        "counts_by_class": {name: counts[name] for name in ATTENTION_CLASSES if counts[name]},
        "counts_by_interruption": {
            name: interruptions[name]
            for name in ("blocking", "popup", "queued", "waiting")
            if interruptions[name]
        },
        "highest_class": items[0].attention_class if items else None,
        "rising": [
            item.source_id
            for item in items[:_MAX_ITEMS]
            if item.attention_class == "time_sensitive"
        ],
        "waiting_quality": _waiting_quality(items),
        "truncated": truncated,
        # Honest source status: HITL pauses need the canonical graph spine.
        # When it is down, failed-Run items may still populate the page.
        "hitl_unavailable": hitl_unavailable,
        "dismissed_count": dismissed_count,
    }


def _public(item: _Item, rank: int) -> dict[str, Any]:
    return {
        "source_kind": item.source_kind,
        "source_id": item.source_id,
        "workspace_id": item.workspace_id,
        "attention_class": item.attention_class,
        "interruption": INTERRUPTION_FOR_CLASS.get(item.attention_class, "queued"),
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
    include_dismissed: bool = False,
) -> dict[str, Any] | None:
    """The caller's Attention items in one Workspace, or None when not a member.

    None is also the answer for a Workspace that does not exist, so a caller
    cannot tell the two apart. Counts cover everything scanned; `rising`
    names only returned items. `truncated` means the result may be partial:
    the record ceiling stopped the walk, or `items` was cut to the page cap.
    Deferred/dismissed source ids are filtered unless ``include_dismissed``.
    """
    now = settlement_time(now)
    if not await is_member(user_id, workspace_id):
        return None
    paused, scan_capped, hitl_unavailable = await _paused_records(user_id, workspace_id)
    items = [_human_item(record, pending, now=now, horizon=horizon) for record, pending in paused]
    items.extend(await _failed_runs(user_id, workspace_id))
    # MessageBoard + OptimizationInbox MERGE (#1049): same projection, no
    # second lifecycle store. Proactive/optimizer suggestions default to Waiting.
    items.extend(_message_items(workspace_id=workspace_id))
    items.extend(_optimizer_items(workspace_id=workspace_id))
    hidden = dismissed_source_ids(workspace_id)
    dismissed_count = 0
    if hidden and not include_dismissed:
        kept: list[_Item] = []
        for item in items:
            if (item.source_kind, item.source_id) in hidden:
                dismissed_count += 1
            else:
                kept.append(item)
        items = kept
    elif hidden:
        dismissed_count = sum(1 for item in items if (item.source_kind, item.source_id) in hidden)
    items.sort(key=_Item.sort_key)
    truncated = scan_capped or len(items) > _MAX_ITEMS
    return {
        "workspace_id": workspace_id,
        "items": [_public(item, rank) for rank, item in enumerate(items[:_MAX_ITEMS], start=1)],
        "summary": _summary(
            items,
            truncated=truncated,
            hitl_unavailable=hitl_unavailable,
            dismissed_count=dismissed_count,
        ),
    }
