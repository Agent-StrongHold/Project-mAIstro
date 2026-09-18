"""The brief interview as ordinary chat turns (SPEC-091726-7c2a, #53).

`routes/chat.py` asks this module, before it calls a model, whether the turn
belongs to the brief interview for the caller's workspace. It does when an
interview is already open there, or when the turn asks for work to be made.
Then the reply is the interview's, not a model's: the next question, a
reflection of what was just recorded, the summary once every required field
is known, or the draft once the person says commit. Nothing here writes a
Goal; the draft is what the Goal and CreativeBrief writers (#458, #774) will
consume, and the reply says so.

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
    BriefIncompleteError,
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
_NOT_WRITTEN = (
    "Nothing is written beyond this draft yet: the Goal and CreativeBrief writers are "
    "#458 and #774, and this draft is what they will consume."
)


@dataclass(frozen=True)
class BriefTurn:
    """What the chat surface shows for a turn the interview answered."""

    text: str
    event: str
    brief: dict[str, Any]
    draft: dict[str, Any] | None = None
    citations: list[str] = field(default_factory=list)

    def payload(self) -> dict[str, Any]:
        out: dict[str, Any] = {"type": "brief", "event": self.event, **self.brief}
        if self.draft is not None:
            out["draft"] = self.draft
            out["written"] = []
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
    text = (
        "Here's what I'd commit, and nothing is written until you say so. " + "; ".join(lines) + "."
    )
    if assumed:
        text += " I assumed " + ", ".join(assumed) + "; say 'change ...' to fix any of them."
    return text + " Say 'commit it' to commit, or tell me what to change."


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
    return ""


def _draft_text(draft: dict[str, Any]) -> str:
    fields = "; ".join(f"{_label(k).capitalize()}: {v}" for k, v in draft["fields"].items())
    assumed = ", ".join(_label(k) for k in draft["assumed"]) or "nothing"
    return (
        f"Committed as a draft. {fields}. Assumed: {assumed}. Notes: "
        f"{'; '.join(draft['notes']) or 'none'}. {_NOT_WRITTEN}"
    )


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


def _drafted(user_id: str, workspace_id: str, state: BriefInterview) -> BriefTurn | None:
    try:
        draft = commit_brief(_SCRIPT, state)
    except BriefIncompleteError:  # pragma: no cover - brief_ready() guards this
        return None
    brief_store.clear_interview(user_id, workspace_id)
    return BriefTurn(
        text=_draft_text(draft),
        event="drafted",
        brief=_view(None),
        draft=draft,
        citations=["draft produced", "written: nothing (no Goal store yet)"],
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
        drafted = _drafted(user_id, workspace_id, state)
        if drafted is not None:
            return drafted
    return _answered(user_id, workspace_id, state, text)
