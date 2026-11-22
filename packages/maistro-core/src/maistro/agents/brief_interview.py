"""Requirements interview before a Goal or CreativeBrief is committed.

The workspace agent does not turn "let's make a new video" into a Goal on
the spot. A Goal needs a desired state, a success condition and a stop
condition before it is a Goal and not a wish, and a CreativeBrief needs a
channel, a source of truth and a deadline before a specialist can draft
against it. Those come out of a conversation: one plain-language question
at a time, free-text answers, answers the record already holds skipped,
"you decide" allowed where a default is defensible and refused where it is
not, and nothing written until the person says commit.

This module is that conversation's state machine. It is deliberately
deterministic (keyword matching, no model call) so the agent's behaviour
is testable and the same on every run; a caller that wants a model to
paraphrase the questions can, but the fields, the routing and the commit
gate live here.

It sits beside :mod:`maistro.agents.program_context`, which is the
*onboarding* interview (what is this workspace?). This one is the
*per-piece-of-work* interview (what exactly do you want made?), and it
does not touch ``ProgramContext``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from maistro.agents.program_context import InterviewTurn

__all__ = [
    "VIDEO_BRIEF_ALIASES",
    "VIDEO_BRIEF_SCRIPT",
    "AnswerSource",
    "BriefAnswer",
    "BriefEvent",
    "BriefField",
    "BriefIncompleteError",
    "BriefInterview",
    "BriefOption",
    "BriefReply",
    "BriefScript",
    "apply_brief_answer",
    "brief_ready",
    "brief_summary",
    "commit_brief",
    "fill_from_record",
    "missing_fields",
    "next_brief_question",
    "start_brief_interview",
]

AnswerSource = Literal["user", "verbatim", "record", "assumed"]
"""Where a brief field's value came from.

``user``     the person's answer matched one of the field's options.
``verbatim`` the person's answer matched nothing and is carried as written.
``record``   the workspace record answered it, so it was never asked.
``assumed``  the person said "you decide" and the field's default was taken.
"""


class BriefOption(BaseModel):
    """One recognised answer for a field: what it is called, and how to spot it."""

    model_config = ConfigDict(frozen=True)

    key: str
    value: str
    patterns: tuple[str, ...]

    def matches(self, text: str) -> bool:
        return any(re.search(p, text, re.IGNORECASE) for p in self.patterns)


class BriefField(BaseModel):
    """One thing the brief must (or may) know, and the question that draws it out."""

    model_config = ConfigDict(frozen=True)

    key: str
    label: str
    question: str
    required: bool = True
    options: tuple[BriefOption, ...] = ()
    #: What "you decide" assumes. ``None`` means the field cannot be assumed:
    #: the interview refuses and asks again.
    default: str | None = None
    #: Key into the caller's ``record`` mapping. When the record has a value
    #: under it, the field is filled from the record and never asked.
    record_key: str | None = None

    def parse(self, text: str) -> BriefOption | None:
        for opt in self.options:
            if opt.matches(text):
                return opt
        return None


class BriefScript(BaseModel):
    """An ordered set of fields; required ones gate the commit."""

    model_config = ConfigDict(frozen=True)

    id: str
    fields: tuple[BriefField, ...]

    def field(self, key: str) -> BriefField | None:
        for f in self.fields:
            if f.key == key:
                return f
        return None

    @property
    def required_keys(self) -> tuple[str, ...]:
        return tuple(f.key for f in self.fields if f.required)


class BriefAnswer(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: str
    source: AnswerSource
    option: str | None = None


class BriefInterview(BaseModel):
    """The conversation so far. Immutable updates, like ``ProgramContext``."""

    model_config = ConfigDict(extra="ignore")

    script_id: str
    opening: str
    answers: dict[str, BriefAnswer] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)
    transcript: list[InterviewTurn] = Field(default_factory=list)
    dropped: bool = False
    updated_at: str = ""


BriefEvent = Literal[
    "answered",
    "routed",
    "assumed",
    "cannot_assume",
    "changed",
    "noted",
    "dropped",
    "already_dropped",
]


class BriefReply(BaseModel):
    """What one turn did: the new state, the event, and the field it touched."""

    model_config = ConfigDict(frozen=True)

    state: BriefInterview
    event: BriefEvent
    field: str | None = None


class BriefIncompleteError(ValueError):
    """Raised when a commit is attempted before every required field is known."""

    def __init__(self, missing: tuple[str, ...]) -> None:
        self.missing = missing
        super().__init__(f"brief interview incomplete; missing: {', '.join(missing)}")


_DROP = re.compile(r"^\s*(never\s?mind|cancel|drop\s?it|forget\s?it|stop)\b", re.IGNORECASE)
_ASSUME = re.compile(
    r"^\s*(you\s+decide|skip|whatever|don.t\s+care|up\s+to\s+you|your\s+call|not\s+sure|dunno)\b",
    re.IGNORECASE,
)
_CHANGE = re.compile(
    r"^\s*(?:change|actually|switch|make\s+it)[,:]?\s+(?:the\s+)?(?P<field>[a-z_]+)"
    r"\b\s*(?:to|:|is|should\s+be|,)?\s*(?P<rest>.*)$",
    re.IGNORECASE | re.DOTALL,
)
_VERBATIM_LEAD = re.compile(r"^\s*(?:(?:it.s|it\s+is|about|the)\s+)+", re.IGNORECASE)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _require_script(script: BriefScript, state: BriefInterview) -> None:
    """An interview answers one script; applying another's fields to it is a bug."""
    if state.script_id != script.id:
        raise ValueError(f"interview is for script {state.script_id!r}, not {script.id!r}")


def _turn(state: BriefInterview, role: str, text: str) -> list[InterviewTurn]:
    return [*state.transcript, InterviewTurn(role=role, text=text, at=_now())]


def _with_answer(
    state: BriefInterview,
    key: str,
    answer: BriefAnswer,
    *,
    said: str | None = None,
) -> BriefInterview:
    transcript = _turn(state, "user", said) if said is not None else state.transcript
    return state.model_copy(
        update={
            "answers": {**state.answers, key: answer},
            "transcript": transcript,
            "updated_at": _now(),
        }
    )


def start_brief_interview(
    script: BriefScript,
    opening: str,
    *,
    record: Mapping[str, str] | None = None,
) -> BriefInterview:
    """Open the interview from the turn that asked for work.

    Anything the opening turn already says is taken from it, so a person who
    says "a reel about grouting, before the market" is not asked which
    channel or when. Anything the ``record`` answers (keyed by each field's
    ``record_key``) is filled from it and marked so, and never asked.
    """
    state = BriefInterview(
        script_id=script.id,
        opening=opening.strip(),
        transcript=[InterviewTurn(role="user", text=opening.strip(), at=_now())],
        updated_at=_now(),
    )
    for f in script.fields:
        opt = f.parse(opening)
        if opt is not None:
            state = _with_answer(
                state, f.key, BriefAnswer(value=opt.value, source="user", option=opt.key)
            )
    return fill_from_record(script, state, record or {})


def fill_from_record(
    script: BriefScript, state: BriefInterview, record: Mapping[str, str]
) -> BriefInterview:
    """Answer from the workspace record whatever it can, so it is never asked.

    Callers run this at the start and again whenever an answer lets the
    record say more (once the subject is known, the record may know the
    source footage for it). A field the person already answered is left
    alone; a field the record answered earlier is refreshed.
    """
    for f in script.fields:
        if f.record_key is None:
            continue
        existing = state.answers.get(f.key)
        if existing is not None and existing.source != "record":
            continue
        found = record.get(f.record_key)
        if found and (existing is None or existing.value != found):
            state = _with_answer(state, f.key, BriefAnswer(value=found, source="record"))
    return state


def missing_fields(script: BriefScript, state: BriefInterview) -> tuple[str, ...]:
    return tuple(k for k in script.required_keys if k not in state.answers)


def brief_ready(script: BriefScript, state: BriefInterview) -> bool:
    return not state.dropped and not missing_fields(script, state)


def next_brief_question(script: BriefScript, state: BriefInterview) -> BriefField | None:
    """The first required field the record and the person have not answered."""
    if state.dropped:
        return None
    for f in script.fields:
        if f.required and f.key not in state.answers:
            return f
    return None


def _assume(script: BriefScript, state: BriefInterview, f: BriefField, said: str) -> BriefReply:
    if f.default is None:
        return BriefReply(
            state=state.model_copy(update={"transcript": _turn(state, "user", said)}),
            event="cannot_assume",
            field=f.key,
        )
    new = _with_answer(state, f.key, BriefAnswer(value=f.default, source="assumed"), said=said)
    return BriefReply(state=new, event="assumed", field=f.key)


def _set_from_text(
    state: BriefInterview, f: BriefField, text: str, *, said: str
) -> tuple[BriefInterview, BriefAnswer]:
    opt = f.parse(text)
    if opt is not None:
        ans = BriefAnswer(value=opt.value, source="user", option=opt.key)
    else:
        ans = BriefAnswer(value=_VERBATIM_LEAD.sub("", text.strip()), source="verbatim")
    return _with_answer(state, f.key, ans, said=said), ans


def _change(
    script: BriefScript,
    state: BriefInterview,
    said: str,
    aliases: Mapping[str, str] | None,
) -> BriefReply | None:
    m = _CHANGE.match(said)
    if not m:
        return None
    name = m.group("field").lower()
    key = (aliases or {}).get(name, name)
    f = script.field(key)
    if f is None:
        return None
    rest = m.group("rest").strip()
    if not rest:
        new = state.model_copy(
            update={
                "answers": {k: v for k, v in state.answers.items() if k != key},
                "transcript": _turn(state, "user", said),
            }
        )
        return BriefReply(state=new, event="changed", field=key)
    new, _ = _set_from_text(state, f, rest, said=said)
    return BriefReply(state=new, event="changed", field=key)


def _after_required(script: BriefScript, state: BriefInterview, said: str) -> BriefReply:
    """Required fields are all known: a matching answer sets an optional
    field; anything else is a note on the brief, never a Goal change."""
    for f in script.fields:
        if f.required or f.key in state.answers:
            continue
        if f.parse(said) is not None:
            new, _ = _set_from_text(state, f, said, said=said)
            return BriefReply(state=new, event="answered", field=f.key)
    new = state.model_copy(
        update={"notes": [*state.notes, said], "transcript": _turn(state, "user", said)}
    )
    return BriefReply(state=new, event="noted")


def _route_elsewhere(
    script: BriefScript, state: BriefInterview, current: BriefField, said: str
) -> BriefReply | None:
    """An answer that fits some other open required field goes there; the
    current question stands."""
    for other in script.fields:
        if other.key == current.key or not other.required or other.key in state.answers:
            continue
        if other.parse(said) is not None:
            new, _ = _set_from_text(state, other, said, said=said)
            return BriefReply(state=new, event="routed", field=other.key)
    return None


def apply_brief_answer(
    script: BriefScript,
    state: BriefInterview,
    text: str,
    *,
    aliases: Mapping[str, str] | None = None,
) -> BriefReply:
    """Take one free-text turn and move the interview.

    In order: "never mind" drops the interview (nothing was ever written, so
    there is nothing to undo); "change <field> to <x>" re-answers any field,
    open or not; "you decide" takes the current field's default or refuses
    when it has none; an answer that fits the current field is recorded; an
    answer that fits some *other* open required field goes there instead and
    the current question stands; anything else is carried verbatim. Once
    every required field is known, further turns are notes on the brief.
    """
    _require_script(script, state)
    said = text.strip()
    if state.dropped:
        return BriefReply(state=state, event="already_dropped")
    if not said:
        return BriefReply(state=state, event="noted")
    if _DROP.match(said):
        new = state.model_copy(update={"dropped": True, "transcript": _turn(state, "user", said)})
        return BriefReply(state=new, event="dropped")
    changed = _change(script, state, said, aliases)
    if changed is not None:
        return changed
    current = next_brief_question(script, state)
    if current is None:
        return _after_required(script, state, said)
    if _ASSUME.match(said):
        return _assume(script, state, current, said)
    if current.parse(said) is None:
        routed = _route_elsewhere(script, state, current, said)
        if routed is not None:
            return routed
    new, _ = _set_from_text(state, current, said, said=said)
    return BriefReply(state=new, event="answered", field=current.key)


def brief_summary(script: BriefScript, state: BriefInterview) -> dict[str, Any]:
    """The "brief so far": every field with its value and where it came from.

    Open required fields show ``"open"``; unanswered optional fields show
    their default as ``"assumed"`` so the person can see what will be taken
    for granted before they commit.
    """
    _require_script(script, state)
    fields: list[dict[str, Any]] = []
    known = 0
    for f in script.fields:
        ans = state.answers.get(f.key)
        if ans is not None:
            fields.append(
                {
                    "key": f.key,
                    "label": f.label,
                    "value": ans.value,
                    "source": ans.source,
                    "option": ans.option,
                }
            )
            if f.required:
                known += 1
        elif f.required:
            fields.append({"key": f.key, "label": f.label, "value": None, "source": "open"})
        else:
            fields.append({"key": f.key, "label": f.label, "value": f.default, "source": "assumed"})
    return {
        "script": script.id,
        "known": known,
        "needed": len(script.required_keys),
        "ready": brief_ready(script, state),
        "dropped": state.dropped,
        "fields": fields,
        "notes": list(state.notes),
    }


def commit_brief(script: BriefScript, state: BriefInterview) -> dict[str, Any]:
    """Produce the brief draft a Goal and CreativeBrief are written from.

    Refuses, with the missing field keys, unless every required field is
    known. This is the gate: nothing upstream should mint a Goal from an
    interview that this function would not commit.
    """
    _require_script(script, state)
    if state.dropped:
        raise BriefIncompleteError(("dropped",))
    missing = missing_fields(script, state)
    if missing:
        raise BriefIncompleteError(missing)
    values: dict[str, str] = {}
    sources: dict[str, AnswerSource] = {}
    options: dict[str, str] = {}
    assumed: list[str] = []
    for f in script.fields:
        ans = state.answers.get(f.key)
        if ans is None:
            if f.default is None:
                continue
            values[f.key] = f.default
            sources[f.key] = "assumed"
            assumed.append(f.key)
            continue
        values[f.key] = ans.value
        sources[f.key] = ans.source
        if ans.option is not None:
            options[f.key] = ans.option
        if ans.source == "assumed":
            assumed.append(f.key)
    return {
        "script": state.script_id,
        "opening": state.opening,
        "fields": values,
        "sources": sources,
        "options": options,
        "assumed": assumed,
        "notes": list(state.notes),
        "turns": len(state.transcript),
    }


# ---------------------------------------------------------------------------
# The first script: a video for a creator workspace.
# ---------------------------------------------------------------------------

VIDEO_BRIEF_SCRIPT = BriefScript(
    id="video_brief",
    fields=(
        BriefField(
            key="subject",
            label="Subject",
            question="What's the video about? A thing you make, a plant, a fix, anything.",
        ),
        BriefField(
            key="outcome",
            label="Outcome",
            question="What should it do for you: teach something, sell something, "
            "or show the making?",
            options=(
                BriefOption(
                    key="teach",
                    value="Teach it",
                    patterns=(r"\bteach", r"how[- ]to", r"tutorial", r"\bguide", r"\btips?\b"),
                ),
                BriefOption(
                    key="sell",
                    value="Sell it",
                    patterns=(r"\bsell", r"listing", r"\bshop\b", r"\bbuy\b", r"\bdrop\b"),
                ),
                BriefOption(
                    key="process",
                    value="Show the making",
                    patterns=(r"process", r"\bmaking\b", r"behind", r"\bshow\b"),
                ),
            ),
            default="Teach it",
        ),
        BriefField(
            key="channel",
            label="Channel",
            question="Where does it live? That sets length and frame shape.",
            options=(
                BriefOption(
                    key="reel",
                    value="a 30-second vertical reel",
                    patterns=(
                        r"\breel",
                        r"instagram",
                        r"\binsta\b",
                        r"\big\b",
                        r"tiktok",
                        r"short",
                    ),
                ),
                BriefOption(
                    key="yt",
                    value="a YouTube video, up to 6 minutes, landscape",
                    patterns=(r"youtube", r"\byt\b", r"\blong\b", r"landscape"),
                ),
                BriefOption(
                    key="site",
                    value="a 2-minute landscape embed for the guide page",
                    patterns=(r"\bsite\b", r"website", r"guide page", r"\bembed\b", r"\bblog\b"),
                ),
            ),
            default="a 30-second vertical reel",
        ),
        BriefField(
            key="source",
            label="Source",
            question="What do I work from? Footage or photos you already have, "
            "or is this a fresh shoot?",
            record_key="source",
            default="A fresh shoot; the specialist writes a shot list first",
        ),
        BriefField(
            key="deadline",
            label="Deadline",
            question="When does it need to be out? Before the next market, after it, or a date?",
            options=(
                BriefOption(
                    key="after",
                    value="After the market",
                    patterns=(r"\bafter\b", r"next week", r"following"),
                ),
                BriefOption(
                    key="before",
                    value="Before the market",
                    patterns=(r"\bbefore\b", r"this week", r"saturday", r"market", r"\basap\b"),
                ),
                BriefOption(
                    key="open",
                    value="No date; open until the Goal's stop",
                    patterns=(r"no rush", r"whenever", r"no deadline", r"eventually"),
                ),
            ),
            default="No date; open until the Goal's stop",
        ),
        BriefField(
            key="voice",
            label="Voice",
            question="Your usual voice, or different this time?",
            required=False,
            default="The persona's voice",
        ),
        BriefField(
            key="claims",
            label="Claims",
            question="Anything this must not claim?",
            required=False,
            default="Only what the published guides say; no growth-rate or price claims",
        ),
        BriefField(
            key="mode",
            label="Control",
            question="Do you want to mark up the board, or just see the result?",
            required=False,
            options=(
                BriefOption(
                    key="delegated",
                    value="Delegated: the specialist drafts and cuts; you see the result",
                    patterns=(r"just\s+(do|make|show)", r"you decide", r"delegat", r"surprise"),
                ),
                BriefOption(
                    key="collaborative",
                    value="Collaborative: the specialist drafts, you mark up, nothing publishes",
                    patterns=(r"mark\s?(it|that|them)?\s?up", r"review", r"collab", r"\bnotes\b"),
                ),
                BriefOption(
                    key="direct",
                    value="Direct: you approve every frame before the next",
                    patterns=(r"step by step", r"\bdirect\b", r"each frame", r"approve each"),
                ),
            ),
            default="Collaborative: the specialist drafts, you mark up, nothing publishes",
        ),
    ),
)

#: Plain words a person uses for a field when they say "change the …".
VIDEO_BRIEF_ALIASES: dict[str, str] = {
    "video": "subject",
    "topic": "subject",
    "where": "channel",
    "platform": "channel",
    "footage": "source",
    "when": "deadline",
    "tone": "voice",
    "claim": "claims",
    "control": "mode",
}
