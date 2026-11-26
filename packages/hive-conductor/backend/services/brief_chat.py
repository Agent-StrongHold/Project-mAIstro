"""The brief interview as ordinary chat turns (SPEC-091726-7c2a, #53).

`routes/chat.py` asks this module, before it calls a model, whether the turn
belongs to the brief interview for the caller's workspace. It does when an
interview is already open there, or when the turn asks for work to be made.
Then the reply is the interview's, not a model's: the next question, a
reflection of what was just recorded, the summary once every required field
is known, and — once the person explicitly confirms the reviewed draft — the
commit (#1823). The commit is `services.brief_commit`'s to make: this module
only passes the gate's draft across the one authorized boundary and reports
the truthful outcome. Until that boundary returns a durable result, nothing
is written and the interview stays open; a committed interview is gone and
its Goal is discoverable through the canonical Goal enumeration.

The phrasing is deterministic on purpose (ADR-091726-7c2a): the same answer
gives the same reply on every run, so the behaviour is testable without a
provider. A model may paraphrase later; the fields, the routing and the gate
live in `maistro.agents.brief_interview`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from maistro.agents.brief_interview import (
    VIDEO_BRIEF_ALIASES,
    VIDEO_BRIEF_SCRIPT,
    BriefField,
    BriefInterview,
    BriefReply,
    BriefScript,
    apply_brief_answer,
    brief_ready,
    brief_summary,
    commit_brief,
    next_brief_question,
    start_brief_interview,
)
from services import brief_store
from services.brief_commit import (
    CommitNotAuthorized,
    CommitOutcome,
    CommitRejected,
    commit_draft,
)
from services.workspace_mode import is_workspace_request_authorized

#: A turn that asks for something to be made. Deliberately narrow: a question
#: about the record, or small talk, must reach the model as before.
_WORK_REQUEST = re.compile(
    r"(\b(make|new|start|draft|create|shoot|plan|produce)\b[^.?!]{0,60}"
    r"\b(video|reel|storyboard|post|carousel|guide|tutorial|listing|clip|film)s?\b)"
    r"|(\b(video|reel|storyboard|post|carousel|guide|tutorial|listing|clip|film)s?\b[^.?!]{0,40}"
    r"\b(make|start|draft|create|shoot|plan|produce)\b)",
    re.IGNORECASE,
)
_COMMIT = re.compile(
    r"^\s*(commit( it)?|yes|yep|go( ahead)?|do it|ok(ay)?|sure|that.s it|looks good)\b", re.I
)
_CHANGE_WHAT = re.compile(r"^\s*(change|something|no\b|wrong|different)", re.I)

_SCRIPT: BriefScript = VIDEO_BRIEF_SCRIPT
_ALIASES = VIDEO_BRIEF_ALIASES

_INTRO = (
    "Good. That's new work, so it becomes a Goal I'm accountable for, with a brief "
    "and a run you can watch. Before I commit anything I want to understand it, so a "
    "few questions, one at a time. Say 'you decide' on any of them and I'll assume "
    "something and say so."
)


@dataclass(frozen=True)
class BriefTurn:
    """What the chat surface shows for a turn the interview answered."""

    text: str
    event: str
    brief: dict[str, Any]
    draft: dict[str, Any] | None = None
    commit: dict[str, Any] | None = None
    citations: list[str] = field(default_factory=list)

    @property
    def _written(self) -> list[dict[str, Any]]:
        """The canonical identities this turn actually wrote, truthfully.

        Empty unless the commit is durable (AC-8: the product no longer
        reports a draft as a durable commitment)."""
        c = self.commit or {}
        if c.get("status") not in ("committed", "already_committed"):
            return []
        written: list[dict[str, Any]] = []
        if c.get("goal_id"):
            written.append(
                {
                    "kind": "goal",
                    "goal_id": c["goal_id"],
                    "revision": c.get("goal_revision"),
                }
            )
        if c.get("brief_id"):
            written.append(
                {
                    "kind": "creative_brief",
                    "brief_id": c["brief_id"],
                    "lineage_id": c.get("lineage_id"),
                    "version": c.get("brief_version"),
                }
            )
        return written

    def payload(self) -> dict[str, Any]:
        out: dict[str, Any] = {"type": "brief", "event": self.event, **self.brief}
        if self.draft is not None:
            out["draft"] = self.draft
        out["written"] = self._written
        if self.commit is not None:
            out["commit"] = self.commit
        return out


def _view(state: BriefInterview | None) -> dict[str, Any]:
    if state is None:
        return {"interview": None, "summary": None, "question": None}
    q = next_brief_question(_SCRIPT, state)
    return {
        "interview": state.model_dump(mode="json"),
        "summary": brief_summary(_SCRIPT, state),
        "question": None
        if q is None
        else {
            "key": q.key,
            "label": q.label,
            "question": q.question,
            "options": [{"key": o.key, "value": o.value} for o in q.options],
            "can_assume": q.default is not None,
        },
    }


def _label(key: str) -> str:
    f = _SCRIPT.field(key)
    return f.label.lower() if f else key


def _ask(f: BriefField) -> str:
    return f.question


def _summary_text(state: BriefInterview) -> str:
    s = brief_summary(_SCRIPT, state)
    known = [f for f in s["fields"] if f["source"] not in ("open", "assumed")]
    assumed = [f["label"].lower() for f in s["fields"] if f["source"] == "assumed"]
    lines = [f"{f['label']}: {f['value']}" for f in known]
    # The optional fields take their defaults marked assumed, so this list is
    # empty only when every one of them was answered outright.
    assumed_note = (
        " I assumed " + ", ".join(assumed) + "; say 'change ...' to fix any of them."
        if assumed
        else ""
    )
    return (
        "Here's what I'd commit, and nothing is written until you say so. "
        + "; ".join(lines)
        + "."
        + assumed_note
        + " Say 'commit it' to commit, or tell me what to change."
    )


def _next_text(state: BriefInterview) -> str:
    q = next_brief_question(_SCRIPT, state)
    if q is not None:
        return _ask(q)
    return _summary_text(state)


def _reflect(reply: BriefReply) -> str:
    key = reply.field or ""
    ans = reply.state.answers.get(key)
    label = _label(key)
    value = ans.value if ans else ""
    match reply.event:
        case "answered" if ans and ans.source == "verbatim":
            return f"Noted, as you said it. {label.capitalize()}: '{value}'."
        case "answered" | "changed":
            return f"Got it. {label.capitalize()}: {value}."
        case "routed":
            still = next_brief_question(_SCRIPT, reply.state)
            still_label = still.label.lower() if still else "the current question"
            return (
                f"That sounds like the {label}, so I've put it there: {value}. "
                f"Still need {still_label}."
            )
        case "assumed":
            return f"I'll assume {label}: {value}. Say so if that's wrong."
        case "cannot_assume":
            return (
                "That one I can't assume: I don't start a Goal without knowing what "
                "it's about. A word or two is enough."
            )
        case "noted":
            return "I'll carry that as a note on the brief, not a change to the Goal."
        case _:
            # "dropped" and "started" never reach here; a new event would.
            return ""


def _start(user_id: str, workspace_id: str, text: str) -> BriefTurn:
    state = start_brief_interview(_SCRIPT, text)
    brief_store.save_interview(user_id, workspace_id, state)
    pre = [
        f"{f['label'].lower()}: {f['value']}"
        for f in brief_summary(_SCRIPT, state)["fields"]
        if f["source"] in ("user", "verbatim", "record")
    ]
    intro = _INTRO + (
        " From what you just said I already have " + "; ".join(pre) + "." if pre else ""
    )
    return BriefTurn(
        text=f"{intro} {_next_text(state)}",
        event="started",
        brief=_view(state),
        citations=["interview: video_brief", "no write"],
    )


def _committed_text(outcome: CommitOutcome, draft: dict[str, Any]) -> str:
    assumed = ", ".join(_label(k) for k in draft["assumed"]) or "nothing"
    head = (
        f"Committed. Goal {outcome.goal_id} at revision {outcome.goal_revision}, with "
        f"CreativeBrief {outcome.brief_id} (lineage {outcome.lineage_id}, "
        f"version {outcome.brief_version})."
    )
    if outcome.status == "already_committed":
        head = (
            f"Already committed — this is that same Goal {outcome.goal_id} at "
            f"revision {outcome.goal_revision}, brief {outcome.brief_id} v"
            f"{outcome.brief_version}. Nothing was duplicated."
        )
    tail = (
        f" I assumed {assumed}; say 'change ...' before I start work if any of "
        "those need fixing. I'm accountable for this Goal from here — you'll "
        "find it on the Goals board with this brief attached."
    )
    return f"{head}{tail}"


def _uncommitted_text(outcome: CommitOutcome) -> str:
    if outcome.status == "unavailable":
        return (
            f"I could not commit this yet: {outcome.reason}. Nothing is lost — "
            "your answers are still here, and I haven't written a half-done "
            "Goal. Say 'commit it' again once the durable stores are back."
        )
    return (
        f"The commit did not go through: {outcome.reason}. Nothing was "
        "finalized and your draft is intact — say 'commit it' to try again."
    )


def _refused_turn(reason: str, state: BriefInterview) -> BriefTurn:
    """A refusal that re-confirming cannot fix (authorization, a draft the
    gate no longer accepts). Truthful: nothing was written, the interview is
    still open, and the next step is not 'commit it' again."""
    return BriefTurn(
        text=(
            f"I can't commit this here: {reason} Nothing was written, and your "
            "answers are still open — the Workspace owner is the one who can "
            "turn this draft into a Goal."
        ),
        event="refused",
        brief=_view(state),
        commit={"status": "refused", "reason": reason},
        citations=["commit refused: no write"],
    )


async def _drafted(user_id: str, workspace_id: str, state: BriefInterview) -> BriefTurn:
    """The explicit confirmation: the one write path (SPEC-091726-7c2a + #1823).

    The boundary re-runs the gate, resolves the principal/Project/agent on the
    server, and commits one canonical Goal + one CreativeBrief as a single
    logical, crash-safe commit. The interview is cleared only once the durable
    result is in hand (AC-4): a failed or unavailable commit keeps the
    interview open, so the same 'commit it' can be retried."""
    # Only called once brief_ready() holds, so the gate cannot refuse here.
    draft = commit_brief(_SCRIPT, state)
    try:
        outcome = await commit_draft(user_id, workspace_id, draft, confirmed=True)
    except CommitNotAuthorized as exc:
        return _refused_turn(str(exc), state)
    except CommitRejected as exc:
        return _refused_turn(str(exc), state)
    if outcome.durable:
        brief_store.clear_interview(user_id, workspace_id)
        return BriefTurn(
            text=_committed_text(outcome, draft),
            event="committed",
            brief=_view(None),
            draft=draft,
            commit=outcome.payload(),
            citations=[
                f"goal: {outcome.goal_id} r{outcome.goal_revision}",
                f"brief: {outcome.brief_id} v{outcome.brief_version}",
            ],
        )
    event = "unavailable" if outcome.status == "unavailable" else "failed"
    citations = [f"commit {outcome.status}: retryable"]
    return BriefTurn(
        text=_uncommitted_text(outcome),
        event=event,
        brief=_view(state),
        draft=draft,
        commit=outcome.payload(),
        citations=citations,
    )


def _answered(user_id: str, workspace_id: str, state: BriefInterview, text: str) -> BriefTurn:
    reply = apply_brief_answer(_SCRIPT, state, text, aliases=_ALIASES)
    if reply.event == "dropped":
        brief_store.clear_interview(user_id, workspace_id)
        return BriefTurn(
            text="Dropped. Nothing was committed: no Goal, no brief, no run.",
            event="dropped",
            brief=_view(None),
            citations=["no write"],
        )
    brief_store.save_interview(user_id, workspace_id, reply.state)
    if reply.event == "noted" and brief_ready(_SCRIPT, reply.state) and _CHANGE_WHAT.match(text):
        body = (
            "Which one? Say it like 'change channel to YouTube' or 'change deadline, "
            "after the market'."
        )
    elif reply.event == "cannot_assume":
        body = _reflect(reply)
    else:
        body = f"{_reflect(reply)} {_next_text(reply.state)}".strip()
    return BriefTurn(
        text=body,
        event=reply.event,
        brief=_view(reply.state),
        citations=[f"brief: {reply.field} <- {reply.event}"] if reply.field else ["no write"],
    )


async def brief_turn(user_id: str, workspace_id: str | None, text: str) -> BriefTurn | None:
    """The interview's reply to this turn, or ``None`` when the model should answer.

    ``None`` when no workspace is named, the caller is not a member, no
    interview is open and the turn does not ask for work, or the open
    interview was dropped by an earlier turn (that state is forgotten here).
    """
    if not workspace_id or not text.strip():
        return None
    if not await is_workspace_request_authorized(user_id, workspace_id):
        return None
    state = brief_store.get_interview(user_id, workspace_id)
    if state is not None and state.dropped:
        brief_store.clear_interview(user_id, workspace_id)
        state = None
    if state is None:
        return _start(user_id, workspace_id, text) if _WORK_REQUEST.search(text) else None
    if brief_ready(_SCRIPT, state) and _COMMIT.match(text):
        return await _drafted(user_id, workspace_id, state)
    return _answered(user_id, workspace_id, state, text)
