"""brief_interview.py — the requirements conversation before a Goal is committed.

Acceptance criteria are SPEC-091726-7c2a's. The interview is deterministic
so every scenario below is the same on every run; the record is a plain
mapping, the way the workspace agent would hand it over.
"""

from __future__ import annotations

import pytest

from maistro.agents.brief_interview import (
    VIDEO_BRIEF_ALIASES,
    VIDEO_BRIEF_SCRIPT,
    BriefIncompleteError,
    BriefInterview,
    apply_brief_answer,
    brief_ready,
    brief_summary,
    commit_brief,
    fill_from_record,
    missing_fields,
    next_brief_question,
    start_brief_interview,
)

S = VIDEO_BRIEF_SCRIPT
OPENING = "Let's make a new video, let's start drafting a storyboard"


def _say(state: BriefInterview, text: str) -> BriefInterview:
    return apply_brief_answer(S, state, text, aliases=VIDEO_BRIEF_ALIASES).state


def _answer_all(state: BriefInterview) -> BriefInterview:
    for text in (
        "grouting haze on path stones",
        "teach it",
        "instagram reel",
        "the assembled cut",
        "after the market",
    ):
        state = _say(state, text)
    return state


@pytest.mark.ac("SPEC-091726-7c2a/AC-1")
def test_a_work_request_opens_an_interview_and_nothing_is_committable_yet() -> None:
    state = start_brief_interview(S, OPENING)

    assert not brief_ready(S, state)
    assert missing_fields(S, state) == ("subject", "outcome", "channel", "source", "deadline")
    with pytest.raises(BriefIncompleteError) as exc:
        commit_brief(S, state)
    assert exc.value.missing == ("subject", "outcome", "channel", "source", "deadline")
    # The opening turn is the first line of the transcript: the interview is the run.
    assert state.transcript[0].role == "user"
    assert state.transcript[0].text == OPENING


@pytest.mark.ac("SPEC-091726-7c2a/AC-2")
def test_one_required_question_at_a_time_in_script_order() -> None:
    state = start_brief_interview(S, OPENING)
    asked: list[str] = []
    for text in ("grouting haze", "teach it", "a reel", "the assembled cut", "no rush"):
        q = next_brief_question(S, state)
        assert q is not None
        asked.append(q.key)
        state = _say(state, text)

    assert asked == ["subject", "outcome", "channel", "source", "deadline"]
    assert next_brief_question(S, state) is None, "optional fields are never asked as gates"
    assert brief_ready(S, state)


@pytest.mark.ac("SPEC-091726-7c2a/AC-3")
def test_answers_in_the_opening_turn_or_the_record_are_not_asked() -> None:
    state = start_brief_interview(
        S,
        "New reel about the grouting haze, before the market",
        record={"source": "the assembled cut (run-2278)"},
    )

    assert state.answers["channel"].source == "user"
    assert state.answers["channel"].option == "reel"
    assert state.answers["deadline"].option == "before"
    assert state.answers["source"].source == "record"
    assert state.answers["source"].value == "the assembled cut (run-2278)"
    assert missing_fields(S, state) == ("subject", "outcome")
    assert next_brief_question(S, state) is not None
    assert next_brief_question(S, state).key == "subject"  # type: ignore[union-attr]


@pytest.mark.ac("SPEC-091726-7c2a/AC-3")
def test_the_record_can_answer_later_but_never_overrides_the_person() -> None:
    state = start_brief_interview(S, OPENING)
    state = _say(state, "the vampire frog print")
    state = fill_from_record(S, state, {"source": "6 process photos from August"})
    assert state.answers["source"].source == "record"

    state = _say(state, "change source to I shot new clips yesterday")
    assert state.answers["source"].source == "verbatim"
    state = fill_from_record(S, state, {"source": "6 process photos from August"})
    assert state.answers["source"].value == "I shot new clips yesterday"


@pytest.mark.ac("SPEC-091726-7c2a/AC-4")
def test_free_text_is_matched_to_an_option_or_carried_verbatim() -> None:
    state = start_brief_interview(S, OPENING)
    reply = apply_brief_answer(S, state, "it's about grouting the path stones, the haze thing")
    assert reply.event == "answered"
    assert reply.field == "subject"
    assert reply.state.answers["subject"].source == "verbatim"
    assert reply.state.answers["subject"].value == "grouting the path stones, the haze thing"

    reply = apply_brief_answer(S, reply.state, "I want it to teach people the 20 minute wipe")
    assert reply.event == "answered"
    assert reply.state.answers["outcome"].source == "user"
    assert reply.state.answers["outcome"].value == "Teach it"

    reply = apply_brief_answer(S, reply.state, "somewhere new, a platform you don't know")
    assert reply.state.answers["channel"].source == "verbatim"
    assert reply.state.answers["channel"].value == "somewhere new, a platform you don't know"


@pytest.mark.ac("SPEC-091726-7c2a/AC-5")
def test_an_answer_that_fits_another_open_field_goes_there_and_the_question_stands() -> None:
    state = start_brief_interview(S, OPENING)
    state = _say(state, "grouting haze")
    state = _say(state, "teach it")
    assert next_brief_question(S, state).key == "channel"  # type: ignore[union-attr]

    reply = apply_brief_answer(S, state, "after the market")
    assert reply.event == "routed"
    assert reply.field == "deadline"
    assert reply.still_open == "channel"
    assert reply.state.answers["deadline"].value == "After the market"
    assert "channel" not in reply.state.answers
    assert next_brief_question(S, reply.state).key == "channel"  # type: ignore[union-attr]


@pytest.mark.ac("SPEC-091726-7c2a/AC-6")
def test_you_decide_takes_a_marked_default_and_is_refused_where_none_is_defensible() -> None:
    state = start_brief_interview(S, OPENING)

    refused = apply_brief_answer(S, state, "you decide")
    assert refused.event == "cannot_assume"
    assert refused.field == "subject"
    assert "subject" not in refused.state.answers

    state = _say(refused.state, "the albo cutting")
    assumed = apply_brief_answer(S, state, "up to you")
    assert assumed.event == "assumed"
    assert assumed.field == "outcome"
    assert assumed.state.answers["outcome"].source == "assumed"
    assert assumed.state.answers["outcome"].value == "Teach it"


@pytest.mark.ac("SPEC-091726-7c2a/AC-7")
def test_change_reanswers_any_field_and_never_mind_drops_with_nothing_written() -> None:
    state = _answer_all(start_brief_interview(S, OPENING))
    assert state.answers["channel"].option == "reel"

    changed = apply_brief_answer(S, state, "change channel to youtube", aliases=VIDEO_BRIEF_ALIASES)
    assert changed.event == "changed"
    assert changed.field == "channel"
    assert changed.state.answers["channel"].option == "yt"

    by_alias = apply_brief_answer(
        S, changed.state, "actually, when: no rush", aliases=VIDEO_BRIEF_ALIASES
    )
    assert by_alias.event == "changed"
    assert by_alias.field == "deadline"
    assert by_alias.state.answers["deadline"].option == "open"

    reopened = apply_brief_answer(
        S, by_alias.state, "change the deadline", aliases=VIDEO_BRIEF_ALIASES
    )
    assert reopened.event == "changed"
    assert "deadline" not in reopened.state.answers
    assert next_brief_question(S, reopened.state).key == "deadline"  # type: ignore[union-attr]

    dropped = apply_brief_answer(S, reopened.state, "never mind")
    assert dropped.event == "dropped"
    assert dropped.state.dropped
    assert not brief_ready(S, dropped.state)
    with pytest.raises(BriefIncompleteError) as exc:
        commit_brief(S, dropped.state)
    assert exc.value.missing == ("dropped",)
    assert apply_brief_answer(S, dropped.state, "teach it").event == "already_dropped"


@pytest.mark.ac("SPEC-091726-7c2a/AC-8")
def test_commit_only_when_every_required_field_is_known_and_the_draft_says_what_was_assumed() -> (
    None
):
    state = start_brief_interview(S, OPENING)
    state = _say(state, "grouting haze on path stones")
    state = _say(state, "teach it")
    state = _say(state, "instagram reel")
    state = _say(state, "the assembled cut")
    with pytest.raises(BriefIncompleteError) as exc:
        commit_brief(S, state)
    assert exc.value.missing == ("deadline",)

    state = _say(state, "you decide")
    draft = commit_brief(S, state)

    assert draft["script"] == "video_brief"
    assert draft["opening"] == OPENING
    assert draft["fields"]["subject"] == "grouting haze on path stones"
    assert draft["fields"]["channel"] == "a 30-second vertical reel"
    assert draft["fields"]["deadline"] == "No date; open until the Goal's stop"
    assert draft["fields"]["mode"].startswith("Collaborative")
    assert draft["sources"]["subject"] == "verbatim"
    assert draft["sources"]["deadline"] == "assumed"
    assert draft["sources"]["voice"] == "assumed"
    assert draft["assumed"] == ["deadline", "voice", "claims", "mode"]
    assert draft["turns"] == 6, "opening plus five answers"


@pytest.mark.ac("SPEC-091726-7c2a/AC-9")
def test_once_required_fields_are_known_extra_turns_set_optional_fields_or_become_notes() -> None:
    state = _answer_all(start_brief_interview(S, OPENING))
    assert brief_ready(S, state)

    mode = apply_brief_answer(S, state, "I want to mark it up")
    assert mode.event == "answered"
    assert mode.field == "mode"
    assert mode.state.answers["mode"].option == "collaborative"

    note = apply_brief_answer(S, mode.state, "keep the intro under three seconds")
    assert note.event == "noted"
    assert note.state.notes == ["keep the intro under three seconds"]
    assert missing_fields(S, note.state) == ()

    draft = commit_brief(S, note.state)
    assert draft["notes"] == ["keep the intro under three seconds"]
    assert draft["sources"]["mode"] == "user"
    assert "mode" not in draft["assumed"]


@pytest.mark.ac("SPEC-091726-7c2a/AC-2")
def test_the_brief_so_far_shows_known_open_and_assumed_fields() -> None:
    state = start_brief_interview(S, OPENING, record={"source": "tray B3 log"})
    state = _say(state, "cutting a Thai Constellation node")
    summary = brief_summary(S, state)

    assert summary["known"] == 2
    assert summary["needed"] == 5
    assert not summary["ready"]
    by_key = {f["key"]: f for f in summary["fields"]}
    assert by_key["subject"]["source"] == "verbatim"
    assert by_key["source"] == {
        "key": "source",
        "label": "Source",
        "value": "tray B3 log",
        "source": "record",
    }
    assert by_key["outcome"] == {
        "key": "outcome",
        "label": "Outcome",
        "value": None,
        "source": "open",
    }
    assert by_key["voice"]["source"] == "assumed"
    assert by_key["voice"]["value"] == "The persona's voice"
