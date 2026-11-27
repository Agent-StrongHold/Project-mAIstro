"""The authorized commit boundary for a completed brief interview (#1823).

One application service, and the only writer this product has for turning a
confirmed interview draft into canonical state. Everything upstream
(``services.brief_chat``) produces chat state; everything downstream
(#805 reconciliation decisions, #806 durable wakeups) consumes the canonical
Goal this service commits. The boundary composes the two existing versioned
authorities — the canonical Goal store (`maistro.goals`, #1572) through its
principal-carrying :class:`~maistro.goals.authorization.ScopedGoalStore` seam,
and the CreativeBrief store (`maistro_design.brief_store`, #774) — it does not
define a second Goal or brief store, executor, or scheduler.

A commit is **one logical identity with a durable protocol**, because the two
writes land in two stores that share no transaction:

1. Revalidate the draft (every required field known — the same gate
   ``maistro.agents.brief_interview.commit_brief`` enforces) and require the
   caller's explicit confirmation. The boundary does not trust its caller's
   gatekeeping.
2. Resolve every prerequisite on the server before writing anything: the
   authenticated principal, the canonical Workspace (membership re-checked
   through the canonical authority), the Workspace's Root Project, the stable
   accountable Workspace Agent, the Goal seam and the brief store. Anything
   missing answers :class:`CommitPrerequisiteUnavailable` — the explicit,
   recoverable limitation AC-8 asks for — and nothing is written.
3. Mint the whole identity up front (``goal_id``, ``brief_id``,
   ``lineage_id``) and record it durably in the commit record *before* the
   first write. Fresh intake is brief first, Goal last: a Goal row only ever
   appears after its brief exists, so canonical Goal enumeration can never
   surface a Goal whose creative projection is missing. Crash windows are
   closed by resume-from-record (``_run_protocol``): every step checks
   whether it already happened, by identity rather than by guessing, and
   otherwise retries with the same pre-minted identity — replay, concurrent
   tabs, network loss and process death all resume one logical commit and
   return the same Goal/brief ids (AC-3/AC-4).
4. Mark the record ``committed`` only after both writes landed, then — and
   only then — may the caller discard the interview draft. The chat surface
   clears the interview *after* this service returns a durable outcome
   (AC-4: the only recoverable draft is not discarded before the durable
   result is acknowledged).

A revision of an already-committed Goal (AC-7) rides the same boundary with
``revises=``. When the desired outcome changes, the Goal revision appends
first (compare-and-set, so a stale writer loses cleanly) and the brief
version follows on the same lineage — goal-first is deliberate there: the
brief must bind the *exact* new revision number, which only exists once the
compare-and-set has won. Creative-only changes skip the Goal write entirely
and mint a new brief version over the unchanged Goal revision, exactly the
#774 contract. Either way a revision is canonical, append-only state the
moment it lands, and its brief counterpart is completed by the same resume
protocol; historical revisions and versions are never rewritten.

Provenance is preserved, never invented: the commit record keeps the whole
draft (field values, per-field sources, options, assumed list, notes, opening
turn, turn count); the brief carries the interview's creative content as
references and annotations (persona/design-system references from the
Workspace, notes and source as artifact requirements/annotations); the Goal
revision carries desired state and conditions. Fields the interview never
asked stay empty — the boundary does not invent missing intent (#1823 scope:
"never invent missing required intent").
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import stores

from maistro.goals import GoalRevisionConflict, GoalRevisionDraft
from maistro_design.brief import (
    ArtifactRequest,
    BriefReference,
    BriefVersionConflictError,
    CreativeBrief,
)
from services.model_store import JsonStore
from services.workspace_agent import WorkspaceNotFound, resolve_workspace_agent

logger = logging.getLogger("hive.brief_commit")

#: Durable commit identities/results. Service-owned store beside its only
#: writer (the `stores.py` cutover rule, #1046): new durable state does not
#: join the retiring central module, it registers for persistence here.
_commits = stores.register_json_store(JsonStore("brief_commits"))

#: A follower stops polling a live driver's record and takes the protocol
#: over after this long without an update (a driver killed mid-protocol).
#: Short on purpose: the protocol is resume-safe, so an unnecessary takeover
#: costs a duplicate-skip check, not a second Goal.
_TAKEOVER_SECONDS = 10.0

#: How long a follower waits for a live driver before reporting the commit as
#: still in flight (retryable) rather than blocking the turn forever.
_FOLLOWER_WAIT_SECONDS = 20.0

_POLL_SECONDS = 0.05

#: Live-driver statuses for the wait/takeover race.
_INFLIGHT = frozenset({"pending", "revising"})

#: The statuses an *interrupted* protocol carries: a live driver passes
#: through the stage statuses between writes, and process death (which never
#: runs the ``except`` handler) leaves a record parked on whichever stage it
#: had reached. Startup recovery resumes exactly these — a record whose
#: status is a settled outcome is never auto-driven again:
#: ``committed`` already carries the durable result, and ``failed`` is a
#: caught, reported failure whose draft the user may have cancelled
#: ("never mind") or edited into a replacement afterwards. Auto-driving
#: such a record at startup would commit abandoned intent (AC-2); only the
#: principal's own re-confirmation of the same draft — the chat's "commit
#: it" retry — resumes it, from the recorded stage and with the same
#: pre-minted identities (AC-4: safely retryable).
_RESUMABLE = frozenset({"pending", "revising", "brief_created", "goal_revised", "brief_revised"})


class CommitPrerequisiteUnavailable(RuntimeError):
    """A durable prerequisite is missing: nothing was written, and the same
    confirmation can be retried once the deployment can honour durability.

    This is the explicit recoverable limitation AC-8 asks for — a commit the
    product refuses *loudly* instead of a draft quietly mistaken for a
    durable commitment."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class CommitNotAuthorized(PermissionError):
    """The principal may not commit intake in this Workspace (AC-5).

    One refusal for a non-member, a foreign Workspace, or a blank principal —
    decided through the canonical Workspace authority, never a second
    authorization path."""


class CommitRejected(ValueError):
    """The draft fails the commit gate (missing required fields, unknown
    script, or no explicit confirmation). Nothing was written."""


@dataclass(frozen=True)
class CommitOutcome:
    """The truthful result of one boundary call.

    ``committed`` and ``already_committed`` carry the canonical identities;
    ``unavailable`` (missing prerequisite) and ``failed`` (a write refused
    mid-protocol) carry a ``reason``, wrote nothing new, and remain safely
    retryable — the interview is still open behind them.
    """

    status: str  # committed | already_committed | unavailable | failed
    goal_id: str | None = None
    goal_revision: int | None = None
    brief_id: str | None = None
    lineage_id: str | None = None
    brief_version: int | None = None
    reason: str | None = None
    recovered: bool = False

    @property
    def durable(self) -> bool:
        return self.status in ("committed", "already_committed")

    def payload(self) -> dict[str, Any]:
        out: dict[str, Any] = {"status": self.status, "recovered": self.recovered}
        for name in (
            "goal_id",
            "goal_revision",
            "brief_id",
            "lineage_id",
            "brief_version",
            "reason",
        ):
            value = getattr(self, name)
            if value is not None:
                out[name] = value
        return out


def _now() -> datetime:
    return datetime.now(UTC)


def _iso() -> str:
    return _now().isoformat()


def commit_key(
    user_id: str,
    workspace_id: str,
    draft: dict[str, Any],
    revises: dict[str, Any] | None = None,
) -> str:
    """The deterministic identity of one logical commit.

    Hash of the principal, the Workspace, and the full canonical draft
    content — the same finalized interview, re-confirmed from another tab,
    replayed after network loss, or resumed after process death, hashes to
    the same key and therefore resumes (or returns) the *same* commit rather
    than minting a second Goal (AC-3). A changed answer changes the draft and
    the key, so a genuinely new confirmation is a genuinely new commit.
    """
    body = json.dumps(
        {"user": user_id, "workspace": workspace_id, "draft": draft, "revises": revises},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _script_for(draft: dict[str, Any]) -> Any:
    """The brief script a draft was produced under, by id (#1823 revalidation)."""
    from maistro.agents.brief_interview import VIDEO_BRIEF_SCRIPT

    if draft.get("script") == VIDEO_BRIEF_SCRIPT.id:
        return VIDEO_BRIEF_SCRIPT
    return None


def revalidate_draft(draft: dict[str, Any]) -> None:
    """Re-run the commit gate at the boundary (#1823 scope item 1).

    The chat layer already passed the draft through
    ``brief_interview.commit_brief``; the boundary repeats the check because
    it, not the chat layer, is the writer. Every required field must be known
    and non-blank; optional fields keep the values the draft carries, with
    the ``assumed`` markers that say where each came from."""
    if not isinstance(draft, dict) or not draft:
        raise CommitRejected("no interview draft to commit")
    script = _script_for(draft)
    if script is None:
        raise CommitRejected(f"unknown brief script: {draft.get('script')!r}")
    fields = draft.get("fields")
    if not isinstance(fields, dict):
        raise CommitRejected("draft carries no fields")
    missing = [
        f.key for f in script.fields if f.required and not str(fields.get(f.key) or "").strip()
    ]
    if missing:
        raise CommitRejected(f"interview is incomplete; missing: {', '.join(sorted(missing))}")


def _resolve_goal_reader(override: Any = None) -> Any:
    """The principal-carrying Goal seam, or the explicit limitation.

    Production resolves the embedded core Container's ``goal_reader`` — the
    same canonical Workspace store the product's authorization answers from,
    so one membership decision governs both the chat turn and the commit. A
    process without the Container cannot durably commit Goals and is told so
    instead of silently writing in-process state."""
    if override is not None:
        return override
    try:
        from services.engine import get_engine

        reader = get_engine().goal_reader
    except RuntimeError:
        reader = None
    if reader is None:
        raise CommitPrerequisiteUnavailable(
            "the canonical Goal store is unavailable: the embedded core runtime "
            "is not running, so a committed Goal could not survive a restart"
        )
    return reader


def _resolve_project_store(override: Any = None) -> Any:
    if override is not None:
        return override
    try:
        from services.engine import get_engine

        store = get_engine().project_scope_store
    except RuntimeError:
        store = None
    if store is None:
        raise CommitPrerequisiteUnavailable(
            "the canonical Project store is unavailable: a Goal is parented on "
            "the Workspace's Root Project, which this process cannot resolve"
        )
    return store


def _resolve_brief_store(override: Any = None) -> Any:
    """The CreativeBrief store on the deployment's PostgreSQL (#774).

    ``PgCreativeBriefStore`` composes over the same async session factory the
    design services use. Its insert is PostgreSQL-shaped
    (``CAST(:payload AS jsonb)`` — SQLite's CAST affinity would destroy the
    payload), so a deployment without a configured PostgreSQL database gets
    the explicit limitation rather than a corrupted brief.

    Which spellings count as "PostgreSQL" is the shared configuration's
    call, not a local whitelist: every spelling ``_MIGRATABLE_SCHEMES`` accepts
    normalises through ``to_async_url`` to ``postgresql+asyncpg://``, while
    non-PostgreSQL URLs pass through untouched. Normalising first mirrors
    ``design_service._get_async_engine`` and keeps the two answers — "is a
    database configured" and "is it PostgreSQL" — consistent across services."""
    if override is not None:
        return override
    from maistro.config.database import resolve_database_url, to_async_url

    # ``to_async_url`` rewrites every supported PostgreSQL spelling
    # (``postgresql://``, ``postgres://``, ``postgresql+asyncpg://``,
    # ``postgresql+psycopg://``) to the async driver's scheme and leaves
    # non-PostgreSQL URLs untouched, so this one check accepts exactly what
    # the shared configuration accepts.
    url = to_async_url(resolve_database_url())
    if not url.startswith("postgresql+asyncpg://"):
        raise CommitPrerequisiteUnavailable(
            "CreativeBrief persistence is unavailable: it requires the configured "
            "PostgreSQL database, and no PostgreSQL database URL is set"
        )
    from maistro_design.brief_store import PgCreativeBriefStore
    from services.design_service import _get_async_session_factory

    factory = _get_async_session_factory()
    if factory is None:
        raise CommitPrerequisiteUnavailable(
            "CreativeBrief persistence is unavailable: the design database "
            "session factory did not start"
        )
    return PgCreativeBriefStore(factory)


async def _require_view(user_id: str, workspace_id: str) -> None:
    from services.workspace_mode import is_workspace_request_authorized

    if (
        not user_id
        or not workspace_id
        or not await is_workspace_request_authorized(user_id, workspace_id)
    ):
        raise CommitNotAuthorized(workspace_id or "<no workspace>")


async def _require_committer(user_id: str, workspace_id: str) -> None:
    """The canonical administer decision, through the one authority seam.

    Committing canonical state in a Workspace is an administration act —
    exactly what the Goal seam will re-check when the Goal write lands. This
    check exists so the refusal is a clean, typed one before any identity is
    minted, not a failure discovered mid-protocol (AC-5: a second user cannot
    commit another's intake; a daily-user capability is not broadened)."""
    from maistro.workspaces.authorization import (
        WorkspaceAction,
        WorkspaceAuthorizationDenied,
        WorkspaceAuthorizer,
    )
    from services.workspace_authority import canonical_workspace_store

    if not user_id or not workspace_id:
        raise CommitNotAuthorized(workspace_id or "<no workspace>")
    authorizer = WorkspaceAuthorizer(await canonical_workspace_store())
    try:
        await authorizer.require(user_id, workspace_id, WorkspaceAction.ADMINISTER)
    except WorkspaceAuthorizationDenied:
        raise CommitNotAuthorized(workspace_id) from None


async def _workspace_view(workspace_id: str) -> Any:
    """The canonical Workspace's product view (persona/theme references)."""
    from services import workspace_authority

    view = await workspace_authority.get_view(workspace_id)
    if view is None:
        raise CommitPrerequisiteUnavailable(
            f"workspace {workspace_id} has no canonical presentation record"
        )
    return view


def _revision_draft(draft: dict[str, Any], agent_id: str) -> GoalRevisionDraft:
    """Map the interview draft onto the canonical Goal vocabulary.

    Desired state and conditions only — the Goal is desired state and
    accountability, never work or creative content. The interview's outcome is
    the success condition; its deadline bounds effort unless the person chose
    "open". Notes stay creative-side (the brief carries them)."""
    fields = draft["fields"]
    desired = f"{fields['subject']} — {fields['outcome']}"
    stop: tuple[str, ...] = ()
    if draft.get("options", {}).get("deadline") != "open":
        stop = (f"deadline: {fields['deadline']}",)
    return GoalRevisionDraft(
        desired_state=desired,
        success_conditions=(fields["outcome"],),
        stop_conditions=stop,
        author=agent_id,
    )


def _supervision_constraints(fields: dict[str, Any]) -> tuple[str, ...]:
    """Supervision constraints recorded on the canonical brief.

    Keeps the interview's selected control mode alongside its provenance so
    downstream consumers (creative_nodes.shared_context_from_brief) still see
    the review cadence the user asked for (#mode preservation).
    """
    constraints = [f"source: {fields.get('source', '')}"]
    mode = str(fields.get("mode") or "").strip()
    if mode:
        constraints.append(f"control mode: {mode}")
    return tuple(constraints)


def _brief_from_draft(
    *,
    draft: dict[str, Any],
    workspace_id: str,
    project_id: str,
    goal_id: str,
    goal_revision: int,
    agent_id: str,
    principal_id: str,
    workspace_view: Any,
    brief_id: str,
    lineage_id: str,
    version: int,
    supersedes_brief_id: str | None = None,
) -> CreativeBrief:
    """Build the CreativeBrief version from the draft (#774 contract).

    References, not copies: Persona is the Workspace's canonical persona
    template, the Design System the Workspace's declared theme. Interview
    prose lands in annotation slots; the interview never asked for an
    audience, so none is invented."""
    fields = draft["fields"]
    notes = tuple(draft.get("notes") or ())
    requirements = (*notes, fields.get("source", ""))
    assumed = tuple(draft.get("assumed") or ())
    change_note = (
        f"interview {draft.get('script')} ({draft.get('turns', 0)} turns); "
        f"assumed: {', '.join(assumed) if assumed else 'none'}"
    )
    return CreativeBrief(
        brief_id=brief_id,
        lineage_id=lineage_id,
        version=version,
        supersedes_brief_id=supersedes_brief_id,
        workspace_id=workspace_id,
        project_id=project_id,
        goal_id=goal_id,
        goal_revision=goal_revision,
        goal_owner_agent_id=agent_id,
        persona=BriefReference(
            kind="persona",
            ref_id=workspace_view.persona_template_id,
            workspace_id=workspace_id,
            label="workspace persona",
        ),
        design_system=BriefReference(kind="design_system", ref_id=workspace_view.theme_id),
        success_interpretation=fields["outcome"],
        prohibited_claims=((fields["claims"],) if fields.get("claims") else ()),
        tone_constraints=((fields["voice"],) if fields.get("voice") else ()),
        artifact_requests=(
            ArtifactRequest(
                request_id=f"{lineage_id}-primary",
                channel=fields["channel"],
                format="video",
                requirements=requirements,
            ),
        ),
        supervision_constraints=(*_supervision_constraints(fields),),
        change_note=change_note,
        created_by=principal_id,
    )


def _get_record(key: str) -> dict[str, Any] | None:
    record = _commits.get(key)
    return dict(record) if isinstance(record, dict) else None


def _put_record(record: dict[str, Any]) -> None:
    record["updated_at"] = _iso()
    _commits[record["commit_key"]] = record


def _fresh(record: dict[str, Any], takeover_after: float) -> bool:
    """Whether another driver may still be mid-protocol on this record."""
    try:
        updated = datetime.fromisoformat(str(record["updated_at"]))
    except (KeyError, ValueError):
        return False
    return (_now() - updated).total_seconds() <= takeover_after


async def _wait_for_driver(key: str, takeover_after: float) -> dict[str, Any] | None:
    """Poll a live driver's record until it settles, goes stale, or the wait
    budget runs out. Returns the last record seen."""
    waited = 0.0
    budget = max(_FOLLOWER_WAIT_SECONDS, takeover_after)
    record = _get_record(key)
    while record is not None and record.get("status") in _INFLIGHT and waited < budget:
        if not _fresh(record, takeover_after):
            break
        await asyncio.sleep(_POLL_SECONDS)
        waited += _POLL_SECONDS
        record = _get_record(key)
    return record


def _outcome_from_record(record: dict[str, Any], *, recovered: bool) -> CommitOutcome:
    status = record.get("status")
    if status == "committed":
        result = record.get("result") or {}
        return CommitOutcome(
            status="already_committed" if recovered else "committed",
            goal_id=result.get("goal_id"),
            goal_revision=result.get("goal_revision"),
            brief_id=result.get("brief_id"),
            lineage_id=result.get("lineage_id"),
            brief_version=result.get("brief_version"),
            recovered=recovered,
        )
    return CommitOutcome(
        status="failed",
        reason=str(record.get("failure") or "commit did not complete"),
        recovered=recovered,
    )


async def _run_protocol(
    record: dict[str, Any],
    *,
    goal_reader: Any,
    brief_store: Any,
    workspace_view: Any,
    project_id: str,
    agent_id: str,
) -> CommitOutcome:
    """Resume or drive one commit record to a durable result.

    Every step checks whether it already happened (by identity: the Goal by
    ``goal_id``, the brief by ``brief_id``, an appended revision by its tail)
    before writing, so a crash at any point resumes deterministically into
    the same pair instead of minting a second one (AC-3/AC-4)."""
    fresh = record.get("status") not in _INFLIGHT or int(record.get("attempts") or 0) > 1
    try:
        if record.get("revises") is not None:
            outcome = await _revise_protocol(
                record,
                goal_reader=goal_reader,
                brief_store=brief_store,
                workspace_view=workspace_view,
                project_id=project_id,
                agent_id=agent_id,
            )
        else:
            outcome = await _intake_protocol(
                record,
                goal_reader=goal_reader,
                brief_store=brief_store,
                workspace_view=workspace_view,
                project_id=project_id,
                agent_id=agent_id,
            )
    except CommitPrerequisiteUnavailable as exc:
        record["status"] = "failed"
        record["failure"] = exc.reason
        _put_record(record)
        return CommitOutcome(status="unavailable", reason=exc.reason, recovered=fresh)
    except Exception as exc:
        # ``stage`` keeps the furthest durable progress (which identities
        # exist); ``status`` names the outcome. A failed commit stays safely
        # retryable: the next attempt resumes from the recorded stage.
        record["status"] = "failed"
        record["failure"] = f"{type(exc).__name__}: {exc}"
        _put_record(record)
        logger.warning(
            "brief_commit_failed key=%s workspace=%s attempt=%s: %s",
            record.get("commit_key"),
            record.get("workspace_id"),
            record.get("attempts"),
            record["failure"],
        )
        return CommitOutcome(status="failed", reason=record["failure"], recovered=fresh)
    return outcome


def _mark_committed(record: dict[str, Any], result: dict[str, Any]) -> CommitOutcome:
    record["status"] = "committed"
    record["result"] = {**result, "committed_at": _iso()}
    _put_record(record)
    logger.info(
        "brief_committed key=%s workspace=%s goal=%s revision=%s brief=%s v%s",
        record["commit_key"],
        record["workspace_id"],
        result["goal_id"],
        result["goal_revision"],
        result["brief_id"],
        result["brief_version"],
    )
    return _outcome_from_record(record, recovered=False)


async def _intake_protocol(
    record: dict[str, Any],
    *,
    goal_reader: Any,
    brief_store: Any,
    workspace_view: Any,
    project_id: str,
    agent_id: str,
) -> CommitOutcome:
    """Fresh intake: brief first, Goal last.

    Order is the pair-completeness invariant: the canonical Goal row only
    appears once its brief exists, so Goal enumeration never exposes a Goal
    whose creative projection is missing. Between-writes crashes resume from
    the record: a recorded-but-uncreated identity is created; an
    already-created one is adopted by its id."""
    workspace_id = record["workspace_id"]
    user_id = record["user_id"]
    goal_id = record["goal_id"]
    brief_id = record["brief_id"]
    lineage_id = record["lineage_id"]

    # Step 1 — the brief (pre-minted identity, bound to Goal revision 1).
    brief = await brief_store.get(brief_id, workspace_id=workspace_id)
    if brief is None:
        brief = _brief_from_draft(
            draft=record["draft"],
            workspace_id=workspace_id,
            project_id=project_id,
            goal_id=goal_id,
            goal_revision=1,
            agent_id=agent_id,
            principal_id=user_id,
            workspace_view=workspace_view,
            brief_id=brief_id,
            lineage_id=lineage_id,
            version=1,
        )
        try:
            brief = await brief_store.create(brief)
        except BriefVersionConflictError:
            # A follower can take a still-live driver's record over (the
            # staleness heuristic cannot tell a slow driver from a dead one)
            # and reach this insert while the twin driver's insert for the
            # same pre-minted identity is still in flight. The loser of the
            # unique race adopts the winner's row — a takeover costs a
            # duplicate-skip check, not a failed logical commit. A conflict
            # without our identity (the re-read misses) is genuine: re-raise.
            brief = await brief_store.get(brief_id, workspace_id=workspace_id)
            if brief is None:
                raise
    record["stage"] = "brief_created"
    record["status"] = "brief_created"
    _put_record(record)

    # Step 2 — the canonical Goal, the write that completes the pair.
    goal = None
    try:
        goal = await goal_reader.get_goal(goal_id, principal_id=user_id)
    except LookupError:
        goal = None
    if goal is None:
        try:
            goal = await goal_reader.create_goal(
                principal_id=user_id,
                workspace_id=workspace_id,
                project_id=project_id,
                agent_id=agent_id,
                draft=_revision_draft(record["draft"], agent_id),
                goal_id=goal_id,
            )
        except Exception:
            # The same takeover race, at the insert that completes the pair:
            # the twin driver's row for this record's pre-minted goal_id
            # landed between our check and our insert (the unique index
            # serializes them; the loser sees the violation). A row under our
            # own pre-minted id is by definition this logical commit's write
            # — adopt it. Any other failure (the re-read misses or itself
            # fails) is re-raised so the record keeps its truthful failure.
            try:
                goal = await goal_reader.get_goal(goal_id, principal_id=user_id)
            except LookupError:
                goal = None
            if goal is None:
                raise
    return _mark_committed(
        record,
        {
            "goal_id": goal.goal_id,
            "goal_revision": goal.current_revision,
            "brief_id": brief_id,
            "lineage_id": lineage_id,
            "brief_version": 1,
        },
    )


async def _adopt_revision_tail(
    goal: Any,
    *,
    goal_reader: Any,
    goal_id: str,
    user_id: str,
    expected_revision: int,
    new_draft: GoalRevisionDraft,
) -> int:
    """Adopt the appended tail iff it is this commit's revision — the
    successor the CAS append would have minted, with the complete content
    this draft produces (a crash that landed the append but not the record
    update, or the twin driver a takeover race handed the append to).
    desired_state alone is not unique (subject/outcome shared, deadline
    differs), so every field is compared; anything else means another
    writer moved the Goal."""
    revisions = await goal_reader.list_goal_revisions(goal_id, principal_id=user_id)
    tail = revisions[-1] if revisions else None
    if (
        tail is None
        or tail.revision != expected_revision + 1
        or (tail.desired_state, tail.success_conditions, tail.stop_conditions, tail.author)
        != (
            new_draft.desired_state,
            new_draft.success_conditions,
            new_draft.stop_conditions,
            new_draft.author,
        )
    ):
        raise CommitRejected(
            f"goal {goal_id} moved to revision {goal.current_revision}; "
            "re-check the current state before revising"
        )
    return tail.revision


async def _append_or_adopt_revision(
    goal: Any,
    *,
    goal_reader: Any,
    goal_id: str,
    user_id: str,
    expected_revision: int,
    new_draft: GoalRevisionDraft,
) -> tuple[Any, int]:
    """Append this commit's revision under compare-and-set, or adopt the
    twin that already appended it.

    A follower can take a still-live driver's record over (the staleness
    heuristic cannot tell a slow driver from a dead one) and race the same
    compare-and-set. The loser re-reads and takes the same adoption-or-
    refusal a crash after the append gets: a stale writer still loses
    cleanly (``_adopt_revision_tail`` refuses a foreign tail), a twin
    writing this commit's own next revision converges."""
    if goal.current_revision == expected_revision:
        try:
            goal = await goal_reader.append_revision(
                goal_id,
                new_draft,
                principal_id=user_id,
                expected_revision=expected_revision,
            )
            return goal, goal.current_revision
        except GoalRevisionConflict:
            goal = await goal_reader.get_goal(goal_id, principal_id=user_id)
    revision = await _adopt_revision_tail(
        goal,
        goal_reader=goal_reader,
        goal_id=goal_id,
        user_id=user_id,
        expected_revision=expected_revision,
        new_draft=new_draft,
    )
    return goal, revision


async def _revise_protocol(
    record: dict[str, Any],
    *,
    goal_reader: Any,
    brief_store: Any,
    workspace_view: Any,
    project_id: str,
    agent_id: str,
) -> CommitOutcome:
    """Revise a committed Goal (AC-7), or its creative projection only.

    ``revises["revise_goal"]`` picks the branch:

    - **Desired outcome changed** — the Goal revision appends first under
      compare-and-set, because the brief must bind the exact new revision
      number; the brief version follows on the same lineage. The append is
      canonical the moment it lands; the brief counterpart is completed by
      the same resume protocol, and the tail check makes a re-run after a
      crash adopt the already-appended revision instead of appending a
      duplicate.
    - **Creative-only change** — no Goal write at all; a new brief version
      over the unchanged Goal revision, per the #774 contract.
    """
    workspace_id = record["workspace_id"]
    user_id = record["user_id"]
    revises = record["revises"]
    goal_id = str(revises["goal_id"])
    expected_revision = int(revises["expected_revision"])
    lineage_id = str(revises["lineage_id"])
    brief_id = record["brief_id"]
    revise_goal = bool(revises.get("revise_goal", True))

    goal = await goal_reader.get_goal(goal_id, principal_id=user_id)
    if str(goal.workspace_id) != workspace_id:
        # ``get_goal``/``append_revision`` authorize against the Goal's own
        # Workspace, so a principal administering two Workspaces could reach
        # across them; pin the Goal to the Workspace this commit is scoped
        # to before any write mutates it under this Workspace's Project,
        # agent and presentation.
        raise CommitRejected(
            f"goal {goal_id} belongs to workspace {goal.workspace_id}, not "
            f"{workspace_id}; revises must stay within the requested Workspace"
        )
    # The lineage must live in the requested Workspace too: both lookups
    # are Workspace-scoped, so a foreign lineage (or brief id) resolves to
    # nothing here. Rejecting before the Goal append keeps a cross-Workspace
    # ``revises`` from minting an orphan brief bound to another Workspace's
    # Goal.
    brief = await brief_store.get(brief_id, workspace_id=workspace_id)
    prior = (
        None
        if brief is not None
        else await brief_store.latest(lineage_id, workspace_id=workspace_id)
    )
    if brief is None and prior is None:
        raise CommitRejected(
            f"lineage {lineage_id} has no CreativeBrief in workspace {workspace_id}; "
            "revises must name a lineage committed in the requested Workspace"
        )
    new_draft = _revision_draft(record["draft"], agent_id)
    if revise_goal:
        goal, revision = await _append_or_adopt_revision(
            goal,
            goal_reader=goal_reader,
            goal_id=goal_id,
            user_id=user_id,
            expected_revision=expected_revision,
            new_draft=new_draft,
        )
    else:
        if goal.current_revision != expected_revision:
            raise CommitRejected(
                f"goal {goal_id} is at revision {goal.current_revision}, not "
                f"{expected_revision}; re-read it before changing the brief"
            )
        revision = goal.current_revision
    record["status"] = "goal_revised" if revise_goal else "brief_revised"
    _put_record(record)

    if brief is None:
        brief = _brief_from_draft(
            draft=record["draft"],
            workspace_id=workspace_id,
            project_id=project_id,
            goal_id=goal_id,
            goal_revision=revision,
            agent_id=agent_id,
            principal_id=user_id,
            workspace_view=workspace_view,
            brief_id=brief_id,
            lineage_id=lineage_id,
            version=(prior.version + 1) if prior else 1,
            supersedes_brief_id=prior.brief_id if prior else None,
        )
        try:
            brief = await brief_store.create(brief)
        except BriefVersionConflictError:
            # The takeover race again: the twin driver's version insert for
            # this record's pre-minted brief id landed first. Adopt it —
            # the version it carries is the one this commit minted.
            brief = await brief_store.get(brief_id, workspace_id=workspace_id)
            if brief is None:
                raise
    return _mark_committed(
        record,
        {
            "goal_id": goal_id,
            "goal_revision": revision,
            "brief_id": brief_id,
            "lineage_id": lineage_id,
            "brief_version": brief.version,
        },
    )


def _begin_attempt(record: dict[str, Any]) -> dict[str, Any]:
    """Mark a record as being driven again (fresh driver, next attempt)."""
    record = dict(record)
    record["driver"] = uuid4().hex
    record["attempts"] = int(record.get("attempts") or 0) + 1
    record["status"] = "pending" if record.get("revises") is None else "revising"
    record.pop("failure", None)
    _put_record(record)
    return record


def _candidate(
    key: str,
    *,
    user_id: str,
    workspace_id: str,
    project_id: str,
    agent_id: str,
    draft: dict[str, Any],
    revises: dict[str, Any] | None,
) -> dict[str, Any]:
    """A fresh commit record: the whole logical identity, minted once and
    recorded before any write, so crash recovery resumes these exact ids
    (AC-3/AC-4)."""
    return {
        "commit_key": key,
        "user_id": user_id,
        "workspace_id": workspace_id,
        "project_id": project_id,
        "agent_id": agent_id,
        "script_id": draft.get("script"),
        "draft": draft,
        "revises": revises,
        "goal_id": uuid4().hex,
        "brief_id": str(uuid4()),
        "lineage_id": revises["lineage_id"] if revises else str(uuid4()),
        "status": "pending",
        "attempts": 0,
        "created_at": _iso(),
        "updated_at": _iso(),
        "driver": uuid4().hex,
    }


async def _acquire(
    key: str, candidate: dict[str, Any], takeover_after: float
) -> dict[str, Any] | None:
    """The record this caller drives, or ``None`` when the commit already
    settled while acquiring it.

    A record another driver inserted is waited on while it is fresh and
    driven (resumed) once it goes stale — a concurrent confirmation and a
    process death converge on the same record either way."""
    record = _get_record(key)
    if record is None:
        if _commits.put_if_absent(key, candidate):
            return candidate
        # A concurrent confirmation inserted first — its record is this
        # commit's record now.
        record = _get_record(key)
    if record is None or record.get("status") == "committed":
        return None
    mine = record.get("driver") == candidate.get("driver")
    if not mine and record.get("status") in _INFLIGHT and _fresh(record, takeover_after):
        # A concurrent confirmation (another tab) is already driving this
        # exact commit; wait for its durable result rather than racing it.
        settled = await _wait_for_driver(key, takeover_after)
        if settled is not None and settled.get("status") == "committed":
            return None
        return settled or record
    return record


async def commit_draft(
    user_id: str,
    workspace_id: str,
    draft: dict[str, Any],
    *,
    confirmed: bool,
    revises: dict[str, Any] | None = None,
    goal_reader: Any = None,
    project_store: Any = None,
    brief_store: Any = None,
    takeover_after: float = _TAKEOVER_SECONDS,
) -> CommitOutcome:
    """Commit a confirmed interview draft to a canonical Goal + CreativeBrief.

    The one authorized commit boundary (#1823). ``confirmed`` is the server's
    record that the user explicitly confirmed the reviewed draft — the chat
    surface sets it only when the confirmation phrase matched; the boundary
    refuses without it. ``revises`` (AC-7) names an already-committed lineage:
    ``{"goal_id", "expected_revision", "lineage_id", "revise_goal"}``.

    Returns a truthful :class:`CommitOutcome`; ``durable`` outcomes clear the
    way for the caller to discard the interview draft, every other outcome
    leaves the interview exactly as it was (safely retryable)."""
    if not confirmed:
        raise CommitRejected("commit refused: the reviewed draft was not confirmed")
    revalidate_draft(draft)
    await _require_committer(user_id, workspace_id)

    try:
        goal_reader = _resolve_goal_reader(goal_reader)
        project_store = _resolve_project_store(project_store)
        brief_store = _resolve_brief_store(brief_store)
        try:
            agent = await resolve_workspace_agent(workspace_id)
        except WorkspaceNotFound as exc:
            raise CommitPrerequisiteUnavailable(
                f"the Workspace's accountable agent could not be resolved: {exc}"
            ) from exc
        workspace_view = await _workspace_view(workspace_id)
        project = await project_store.root_for_workspace(workspace_id)
    except CommitPrerequisiteUnavailable as exc:
        # The explicit recoverable limitation (AC-8): named, nothing written,
        # the interview still open behind it. The chat surface renders this
        # as the truthful 'could not commit yet' turn.
        return CommitOutcome(status="unavailable", reason=exc.reason)

    key = commit_key(user_id, workspace_id, draft, revises)
    record = _get_record(key)
    if record is not None and record.get("status") == "committed":
        # Replayed confirmation (or the response lost on the network): the
        # durable result exists, and the same ids come back (AC-3).
        return _outcome_from_record(record, recovered=True)
    candidate = _candidate(
        key,
        user_id=user_id,
        workspace_id=workspace_id,
        project_id=str(project.project_id),
        agent_id=agent.id,
        draft=draft,
        revises=revises,
    )
    record = await _acquire(key, candidate, takeover_after)
    if record is None:
        record = _get_record(key)
        if record is None:
            raise CommitPrerequisiteUnavailable(
                "the commit record vanished while the commit was settling"
            )
        return _outcome_from_record(record, recovered=True)
    record = _begin_attempt(record)

    return await _run_protocol(
        record,
        goal_reader=goal_reader,
        brief_store=brief_store,
        workspace_view=workspace_view,
        project_id=project.project_id,
        agent_id=agent.id,
    )


async def recover_pending_commits(
    *,
    user_id: str | None = None,
    workspace_id: str | None = None,
    goal_reader: Any = None,
    project_store: Any = None,
    brief_store: Any = None,
) -> list[CommitOutcome]:
    """Resume every interrupted commit record deterministically (AC-4).

    Called after a restart (the app lifespan) and available to operations:
    each interrupted record resumes the same pre-minted identity, so a crash
    before either write, between writes, or after the durable commit but
    before the response all converge on the one logical commit. Recovery is
    the protocol's own completion, not a new authorization decision; the
    per-step authorization still applies inside the seam.

    Settled outcomes are not recovery's to revisit: a ``failed`` attempt was
    caught and reported to its principal in-chat — who may have answered
    "never mind" or edited the draft into a replacement — so it is retried
    only by that principal's explicit re-confirmation, never silently
    completed at startup (the cancelled draft creates no Goal, AC-2; the
    failed commit stays safely retryable, AC-4)."""
    outcomes: list[CommitOutcome] = []
    for key in sorted(_commits.keys()):
        record = _get_record(key)
        # Sweep exactly the interrupted protocol stages: process death never
        # runs the ``except`` handler, so a kill between writes parks a record
        # on ``brief_created``/``goal_revised``/``brief_revised`` (or on a
        # live-driver status) and each resumes into the same pair. A settled
        # outcome — ``committed`` or ``failed`` — is left alone: recovery
        # must not commit intent the principal cancelled or replaced.
        if record is None or record.get("status") not in _RESUMABLE:
            continue
        if user_id is not None and record.get("user_id") != user_id:
            continue
        if workspace_id is not None and record.get("workspace_id") != workspace_id:
            continue
        try:
            goal_reader = _resolve_goal_reader(goal_reader)
            project_store = _resolve_project_store(project_store)
            brief_store = _resolve_brief_store(brief_store)
            workspace_view = await _workspace_view(record["workspace_id"])
            project = await project_store.root_for_workspace(record["workspace_id"])
            agent_id = record.get("agent_id")
            if not agent_id:
                agent_id = (await resolve_workspace_agent(record["workspace_id"])).id
            record = _begin_attempt(record)
            outcome = await _run_protocol(
                record,
                goal_reader=goal_reader,
                brief_store=brief_store,
                workspace_view=workspace_view,
                project_id=project.project_id,
                agent_id=agent_id,
            )
        except CommitPrerequisiteUnavailable as exc:
            outcome = CommitOutcome(status="unavailable", reason=exc.reason, recovered=True)
        except Exception as exc:
            record["status"] = "failed"
            record["failure"] = f"{type(exc).__name__}: {exc}"
            _put_record(record)
            outcome = CommitOutcome(status="failed", reason=record["failure"], recovered=True)
        outcomes.append(outcome)
    return outcomes


async def list_commitments(user_id: str, workspace_id: str) -> list[dict[str, Any]]:
    """The principal's committed intake pairs in one Workspace (AC-6).

    Queryable API state over the commit records: one entry per logical
    commit, canonical identities included, interrupted attempts named as what
    they are (``failed``/in-flight) — never as eligible work."""
    await _require_view(user_id, workspace_id)
    out: list[dict[str, Any]] = []
    for key in list(_commits.keys()):
        record = _get_record(key)
        if record is None or record.get("workspace_id") != workspace_id:
            continue
        if record.get("user_id") != user_id:
            continue
        result = record.get("result") or {}
        out.append(
            {
                "commit_key": key,
                "status": record.get("status"),
                "goal_id": result.get("goal_id"),
                "goal_revision": result.get("goal_revision"),
                "brief_id": result.get("brief_id"),
                "lineage_id": result.get("lineage_id"),
                "brief_version": result.get("brief_version"),
                "committed_at": result.get("committed_at"),
                "failure": record.get("failure"),
            }
        )
    out.sort(key=lambda r: str(r.get("committed_at") or ""))
    return out


def forget_commit(key: str, *, user_id: str) -> bool:
    """Drop one finished commit record. Only the principal's own, and only a
    settled one — an interrupted protocol is recovered, never erased."""
    record = _get_record(key)
    if record is None or record.get("user_id") != user_id:
        return False
    if record.get("status") not in ("committed", "failed"):
        return False
    return _commits.pop(key, None) is not None


__all__ = [
    "CommitNotAuthorized",
    "CommitOutcome",
    "CommitPrerequisiteUnavailable",
    "CommitRejected",
    "commit_draft",
    "commit_key",
    "forget_commit",
    "list_commitments",
    "recover_pending_commits",
    "revalidate_draft",
]
